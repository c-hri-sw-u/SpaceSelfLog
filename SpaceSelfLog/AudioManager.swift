import Foundation
import AVFoundation
import Speech

// MARK: - Noise Level

enum NoiseLevel: String, Codable {
    case quiet    = "quiet"
    case moderate = "moderate"
    case loud     = "loud"
}

// MARK: - AudioManager

/// Audio 1.2: single AVAudioEngine tap → VAD + noise level + optional transcription.
///
/// VAD role (dual):
///   - Trigger — onset/offset fire `onSpeechOnset` / `onSpeechOffset` so callers
///     can adjust capture interval and notify downstream layers.
///   - Tag    — `isSpeechActive` is embedded in every frame's audio_tags.
///
/// Noise level role: tag only (not a trigger).
///   RMS → dB smoothed over a 3-second sliding window → quiet / moderate / loud.
///
/// Transcription: SFSpeechRecognizer, default OFF.
///   Enabled by setting `transcriptionEnabled = true` before `start(dataDirectory:)`.
///   Call `consumeTranscript()` at a Layer 1.5 batch boundary to drain the latest result.
final class AudioManager {

    // MARK: - Public state (read-only outside)

    private(set) var isSpeechActive: Bool = false
    private(set) var currentNoiseLevel: NoiseLevel = .quiet
    private(set) var latestRMS: Float = 0        // raw per-buffer RMS (runs on stateQueue, read externally)
    private(set) var smoothedNoiseDB: Float = -100 // 3-second windowed dB

    /// VAD trigger callbacks — dispatched on main thread.
    var onSpeechOnset:  (() -> Void)?
    var onSpeechOffset: (() -> Void)?

    /// Dictionary for embedding in frame metadata.  Thread-safe via stateQueue.
    var audioTags: [String: Any] {
        var speech = false
        var noise  = NoiseLevel.quiet
        var tx: String? = nil
        stateQueue.sync {
            speech = isSpeechActive
            noise  = currentNoiseLevel
            tx     = latestTranscript
        }
        var result: [String: Any] = [
            "noise_level":     noise.rawValue,
            "speech_detected": speech
        ]
        if let t = tx { result["transcript"] = t }
        return result
    }

    // MARK: - Config

    /// "Low" / "Med" / "High".  May be changed before or during a session.
    var vadSensitivity: String = "Med" {
        didSet { applyVADSensitivity() }
    }

    /// Enable SFSpeechRecognizer transcription.  Set before calling `start(dataDirectory:)`.
    var transcriptionEnabled: Bool = false

    // MARK: - Private — audio engine

    private let audioEngine = AVAudioEngine()
    private let tapBufferSize: AVAudioFrameCount = 1024

    // MARK: - Private — VAD (energy-based RMS threshold with onset/offset hysteresis)

    private(set) var vadThreshold:  Float = 0.02
    private var speechOnsetFrames:  Int   = 3   // consecutive frames above threshold → onset
    private var speechOffsetFrames: Int   = 15  // consecutive frames below threshold → offset

    private var framesAboveThreshold: Int = 0
    private var framesBelowThreshold:  Int = 0
    private var isSpeechActiveInternal = false

    // MARK: - Private — noise level (3-second RMS sliding window)

    private var rmsWindow: [Float] = []
    // window size: 3 s × (sampleRate / bufferSize);  populated after engine starts
    private var noiseWindowMaxSize: Int = 128

    var quietThresholdDB: Float = -50.0
    var loudThresholdDB:  Float = -30.0

    // MARK: - Private — transcription

    private var speechRecognizer:   SFSpeechRecognizer?
    private var recognitionRequest:  SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask:     SFSpeechRecognitionTask?
    private var latestTranscript:    String? = nil

    // MARK: - Private — synchronisation & logging

    private let stateQueue  = DispatchQueue(label: "AudioManager.state",      qos: .userInitiated)
    private let bufferQueue = DispatchQueue(label: "AudioManager.bufferSync", qos: .background)

    private var fileHandle: FileHandle?
    private var csvBuffer:  [String] = []
    // Accessed from audio tap callback and main thread — protect via stateQueue.
    private var _isRunning = false
    private var isRunning: Bool {
        get { stateQueue.sync { _isRunning } }
        set { stateQueue.sync { self._isRunning = newValue } }
    }

    // MARK: - Start / Stop

    func start(dataDirectory: URL) {
        guard !isRunning else { return }
        isRunning = true
        framesAboveThreshold = 0
        framesBelowThreshold  = 0
        isSpeechActiveInternal = false
        rmsWindow.removeAll()

        applyVADSensitivity()
        setupCSV(dataDirectory: dataDirectory)
        setupAudioEngine()
    }

    func stop() {
        guard isRunning else { return }
        isRunning = false

        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)

        stopTranscription()
        flushCSV()
        bufferQueue.sync {
            fileHandle?.closeFile()
            fileHandle = nil
        }
    }

    // MARK: - Transcription lifecycle (VAD-triggered, internal)

    private func stopTranscription() {
        stateQueue.async { [weak self] in
            guard let self = self else { return }
            self.recognitionRequest?.endAudio()
            self.recognitionRequest = nil
            self.recognitionTask?.cancel()
            self.recognitionTask = nil
        }
    }

    // MARK: - Engine setup

    private func setupAudioEngine() {
        do {
            // Configure and activate the session FIRST so the input node reports
            // the correct hardware format when we query it below.
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playAndRecord,
                                    mode: .measurement,
                                    options: [.defaultToSpeaker, .allowBluetoothHFP, .mixWithOthers])
            try session.setActive(true)
        } catch {
            print("AudioManager: session setup failed — \(error)")
            return
        }

        let inputNode = audioEngine.inputNode
        let format    = inputNode.outputFormat(forBus: 0)

        // Compute noise window size from actual sample rate
        let framesPerSecond = format.sampleRate / Double(tapBufferSize)
        noiseWindowMaxSize = max(1, Int(3.0 * framesPerSecond))

        inputNode.installTap(onBus: 0, bufferSize: tapBufferSize, format: format) { [weak self] buffer, _ in
            guard let self = self, self.isRunning else { return }
            self.processBuffer(buffer)
        }

        do {
            try audioEngine.start()
            print("AudioManager: engine started (sampleRate=\(format.sampleRate))")
        } catch {
            print("AudioManager: engine start failed — \(error)")
        }
    }

    // MARK: - Buffer processing

    private func processBuffer(_ buffer: AVAudioPCMBuffer) {
        guard let channelData = buffer.floatChannelData?[0] else { return }
        let frameCount = Int(buffer.frameLength)
        guard frameCount > 0 else { return }

        // RMS of this buffer
        var sumSq: Float = 0
        for i in 0..<frameCount { sumSq += channelData[i] * channelData[i] }
        let rms = (sumSq / Float(frameCount)).squareRoot()

        let timestamp = Date()

        stateQueue.async { [weak self] in
            guard let self = self else { return }
            self.updateVAD(rms: rms, timestamp: timestamp)
            self.updateNoiseLevel(rms: rms)
        }

        // Feed recognizer only during active speech segment (VAD-gated).
        // recognitionRequest is non-nil only between VAD onset and recognition completion.
        // Access recognitionRequest on stateQueue to avoid data race with recognition callbacks.
        stateQueue.async { [weak self] in
            guard let self = self, self.transcriptionEnabled, let request = self.recognitionRequest else { return }
            request.append(buffer)
        }
    }

    // MARK: - VAD state machine  (runs on stateQueue)

    private func updateVAD(rms: Float, timestamp: Date) {
        latestRMS = rms
        if rms >= vadThreshold {
            framesAboveThreshold += 1
            framesBelowThreshold  = 0
            if !isSpeechActiveInternal && framesAboveThreshold >= speechOnsetFrames {
                isSpeechActiveInternal = true
                isSpeechActive         = true
                logEvent(ts: timestamp.timeIntervalSinceReferenceDate, event: "speech_onset", rms: rms)
                DispatchQueue.main.async { [weak self] in
                    guard let self = self else { return }
                    self.onSpeechOnset?()
                    if self.transcriptionEnabled { self.beginRecognition() }
                }
            }
        } else {
            framesBelowThreshold  += 1
            framesAboveThreshold   = 0
            if isSpeechActiveInternal && framesBelowThreshold >= speechOffsetFrames {
                isSpeechActiveInternal = false
                isSpeechActive         = false
                logEvent(ts: timestamp.timeIntervalSinceReferenceDate, event: "speech_offset", rms: rms)
                DispatchQueue.main.async { [weak self] in
                    guard let self = self else { return }
                    self.onSpeechOffset?()
                    // Signal end-of-utterance; recognition task will fire its completion callback.
                    self.recognitionRequest?.endAudio()
                }
            }
        }
    }

    // MARK: - Noise level  (runs on stateQueue)

    private func updateNoiseLevel(rms: Float) {
        rmsWindow.append(rms)
        if rmsWindow.count > noiseWindowMaxSize { rmsWindow.removeFirst() }

        let avg = rmsWindow.reduce(0, +) / Float(rmsWindow.count)
        let dB  = avg > 0 ? 20.0 * log10(avg) : -100.0
        smoothedNoiseDB = dB

        if dB < quietThresholdDB {
            currentNoiseLevel = .quiet
        } else if dB < loudThresholdDB {
            currentNoiseLevel = .moderate
        } else {
            currentNoiseLevel = .loud
        }
    }

    // MARK: - VAD sensitivity

    private func applyVADSensitivity() {
        switch vadSensitivity {
        case "Low":
            vadThreshold      = 0.04
            speechOnsetFrames = 5
            speechOffsetFrames = 20
        case "High":
            vadThreshold      = 0.01
            speechOnsetFrames = 2
            speechOffsetFrames = 10
        default: // "Med"
            vadThreshold      = 0.02
            speechOnsetFrames = 3
            speechOffsetFrames = 15
        }
    }

    // MARK: - Transcription (SFSpeechRecognizer, VAD-triggered)

    private func beginRecognition() {
        // Must run on main thread (called from VAD onset dispatch).
        SFSpeechRecognizer.requestAuthorization { [weak self] status in
            guard let self = self, status == .authorized else {
                print("AudioManager: speech recognition not authorized")
                return
            }
            DispatchQueue.main.async { self.startRecognitionSession() }
        }
    }

    private func startRecognitionSession() {
        guard let recognizer = SFSpeechRecognizer(), recognizer.isAvailable else {
            print("AudioManager: SFSpeechRecognizer unavailable")
            return
        }
        speechRecognizer = recognizer

        // Cancel any leftover session before starting a new one.
        stopTranscription()

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = false  // only final result at utterance end

        let onsetTime = Date()

        let task = recognizer.recognitionTask(with: request) { [weak self] result, error in
            guard let self = self else { return }

            let isFinal = result?.isFinal ?? false
            let hasError = error != nil

            if let result = result {
                let text = result.bestTranscription.formattedString
                if isFinal && !text.isEmpty {
                    let ts = onsetTime.timeIntervalSinceReferenceDate
                    self.stateQueue.async {
                        self.latestTranscript = text
                        self.logEvent(ts: ts, event: "transcript", rms: 0, extra: text)
                    }
                }
            }

            if let error = error {
                // Error code 1110 = "no speech detected" — normal for short/silent segments.
                let nsErr = error as NSError
                if nsErr.code != 1110 {
                    print("AudioManager: recognition error — \(error)")
                }
            }

            // Session complete — clear references on stateQueue to avoid data race with audio tap.
            if isFinal || hasError {
                self.stateQueue.async {
                    self.recognitionRequest = nil
                    self.recognitionTask = nil
                }
            }
        }
        // Assign request and task together on stateQueue so audio tap sees them atomically.
        stateQueue.async { [weak self] in
            self?.recognitionRequest = request
            self?.recognitionTask = task
        }
    }

    // MARK: - CSV event logging

    private func setupCSV(dataDirectory: URL) {
        let url = dataDirectory.appendingPathComponent("audio_events.csv")
        if !FileManager.default.fileExists(atPath: url.path) {
            let header = "timestamp,event,rms,transcript\n"
            try? header.data(using: .utf8)?.write(to: url)
        }
        do {
            fileHandle = try FileHandle(forWritingTo: url)
            fileHandle?.seekToEndOfFile()
        } catch {
            print("AudioManager: failed to open CSV — \(error)")
        }
    }

    /// Log an audio event row.  `extra` is written in the transcript column (empty for non-transcript events).
    private func logEvent(ts: Double, event: String, rms: Float, extra: String = "") {
        // Escape any commas or newlines in the transcript text.
        let safe = extra.replacingOccurrences(of: "\"", with: "\"\"")
        let quotedExtra = extra.isEmpty ? "" : "\"\(safe)\""
        let row = String(format: "%.6f,%@,%.6f,%@\n", ts, event, rms, quotedExtra)
        bufferQueue.async { [weak self] in
            guard let self = self else { return }
            self.csvBuffer.append(row)
            if self.csvBuffer.count >= 20 { self.flushCSVLocked() }
        }
    }

    private func flushCSVLocked() {
        guard let handle = fileHandle, !csvBuffer.isEmpty else { return }
        let joined = csvBuffer.joined()
        csvBuffer.removeAll(keepingCapacity: true)
        if let data = joined.data(using: .utf8) { handle.write(data) }
    }

    private func flushCSV() {
        bufferQueue.sync { flushCSVLocked() }
    }
}
