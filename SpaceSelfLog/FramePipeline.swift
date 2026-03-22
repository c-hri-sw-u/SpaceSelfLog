import Foundation

/// Layer 1 frame capture pipeline.
/// Captures JPEG frames at an adaptive interval and writes each frame + a JSON
/// metadata sidecar to the session directory.
///
/// Interval adaptation — Adaptive Interval (spec 1.1):
///   - Default: runs at maxInterval (stable-scene baseline for pattern accumulation).
///   - Trigger (VAD onset or sustained_motion onset): immediately drop to minInterval.
///   - Trigger clears: ramp gradually back up after each quiet frame:
///       e.g. 3 → 5 → 8 → 13 → 20  (geometric ×1.67, last step clamped to maxInterval)
///   - Trigger fires during ramp-up: immediately return to minInterval and restart ramp.
final class FramePipeline {

    // MARK: - Injected callbacks (set by AppViewModel)

    /// Trigger a single JPEG capture; calls completion with raw JPEG data or nil on failure.
    var capturePhoto: ((@escaping (Data?) -> Void) -> Void)?

    /// Returns the current IMU tags dictionary.
    var getIMUTags: (() -> [String: Any])?

    /// Returns the current audio tags dictionary.
    var getAudioTags: (() -> [String: Any])?

    /// Called on the main thread after each frame is successfully saved to disk.
    /// Receives: (jpegData, audioTags, imuTags, currentInterval)
    var onFrameSaved: ((Data, [String: Any], [String: Any], Int) -> Void)?

    // MARK: - State visible to AppViewModel / status endpoint

    private(set) var currentInterval: Int = 20
    private(set) var totalFramesCaptured: Int = 0
    private(set) var latestFrameFilename: String?
    private(set) var latestFrameTimestamp: String?

    // MARK: - Private

    private var minInterval: Int = 3
    private var maxInterval: Int = 20
    private var frameCounter: Int = 0

    // Ramp-up state: geometric steps from minInterval to maxInterval.
    // rampSequence[0] = minInterval, rampSequence.last = maxInterval.
    // rampIndex tracks our current position; advances after each quiet frame.
    private var rampSequence: [Int] = [3, 20]
    private var rampIndex: Int = 0  // 0 = at minInterval (triggered); last = at maxInterval

    // Trigger state: interval stays at minInterval (rampIndex=0) while either is active.
    private var speechActive: Bool = false
    private var motionActive: Bool = false

    private var sessionDirectory: URL?
    private var captureTimer: Timer?
    private let iso8601: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    // MARK: - Lifecycle

    func start(sessionDirectory: URL, minInterval: Int, maxInterval: Int, rampRatio: Double = 1.67) {
        stop()
        self.sessionDirectory = sessionDirectory
        self.minInterval = minInterval
        self.maxInterval = maxInterval
        self.rampSequence = buildRampSequence(from: minInterval, to: maxInterval, ratio: rampRatio)
        // Start at maxInterval (quiet baseline)
        self.rampIndex = rampSequence.count - 1
        self.currentInterval = maxInterval
        self.totalFramesCaptured = 0
        self.frameCounter = 0
        self.latestFrameFilename = nil
        self.latestFrameTimestamp = nil
        self.speechActive = false
        self.motionActive = false

        let framesDir = sessionDirectory.appendingPathComponent("frames")
        try? FileManager.default.createDirectory(at: framesDir, withIntermediateDirectories: true)

        scheduleNextCapture()
        print("FramePipeline: started — session \(sessionDirectory.lastPathComponent), interval \(currentInterval)s, ramp \(rampSequence)")
    }

    func updateIntervals(minInterval: Int, maxInterval: Int, rampRatio: Double) {
        self.minInterval  = minInterval
        self.maxInterval  = maxInterval
        self.rampSequence = buildRampSequence(from: minInterval, to: maxInterval, ratio: rampRatio)
        // Clamp current ramp index to new sequence bounds
        rampIndex = min(rampIndex, rampSequence.count - 1)
        currentInterval = rampSequence[rampIndex]
    }

    func stop() {
        captureTimer?.invalidate()
        captureTimer = nil
    }

    // MARK: - Ramp sequence builder

    /// Builds a geometric ramp [minInterval, ..., maxInterval].
    /// Each step multiplies the previous by `ratio` until maxInterval is reached.
    private func buildRampSequence(from minI: Int, to maxI: Int, ratio: Double) -> [Int] {
        guard minI < maxI else { return [minI] }
        var steps: [Int] = [minI]
        var current = Double(minI)
        while true {
            current *= ratio
            let next = Int(current.rounded())
            if next >= maxI {
                steps.append(maxI)
                break
            }
            steps.append(next)
        }
        return steps
    }

    // MARK: - Trigger handling (IMU + VAD)

    /// Called by AppViewModel whenever IMU motion state transitions.
    func handleMotionStateChange(_ state: MotionState) {
        motionActive = (state == .sustained_motion)
        handleTriggerChange(reason: state.rawValue)
    }

    /// Called by AppViewModel on VAD onset (speechDetected=true) or offset (false).
    func handleVADStateChange(speechDetected: Bool) {
        speechActive = speechDetected
        handleTriggerChange(reason: speechDetected ? "speech_onset" : "speech_offset")
    }

    /// On trigger fires: immediately drop to minInterval (ramp index 0) and restart timer.
    /// On trigger clears: do nothing here — ramp-up happens one step per quiet frame in performCapture.
    private func handleTriggerChange(reason: String) {
        guard motionActive || speechActive else { return }  // trigger cleared — handled post-capture
        guard rampIndex != 0 else { return }                // already at minInterval
        rampIndex = 0
        currentInterval = rampSequence[0]
        print("FramePipeline: trigger → \(currentInterval)s (\(reason))")
        captureTimer?.invalidate()
        scheduleNextCapture()
    }

    // MARK: - Capture loop

    private func scheduleNextCapture() {
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            self.captureTimer = Timer.scheduledTimer(
                withTimeInterval: Double(self.currentInterval),
                repeats: false
            ) { [weak self] _ in
                self?.performCapture()
            }
        }
    }

    private func performCapture() {
        capturePhoto? { [weak self] data in
            // completion fires on CameraManager.outputQueue — hop back to main
            // before touching any FramePipeline state.
            DispatchQueue.main.async { [weak self] in
                guard let self = self else { return }
                if let data = data {
                    self.saveFrame(jpegData: data, capturedAt: Date())
                }
                // Ramp-up: advance one step after each quiet frame.
                if !(self.motionActive || self.speechActive) {
                    let lastIndex = self.rampSequence.count - 1
                    if self.rampIndex < lastIndex {
                        self.rampIndex += 1
                        self.currentInterval = self.rampSequence[self.rampIndex]
                        print("FramePipeline: ramp-up → \(self.currentInterval)s")
                    }
                }
                self.scheduleNextCapture()
            }
        }
    }

    // MARK: - Disk write

    // Called on main thread.
    private func saveFrame(jpegData: Data, capturedAt: Date) {
        guard let dir = sessionDirectory else { return }

        frameCounter += 1
        totalFramesCaptured += 1

        let filename = String(format: "frame_%04d.jpg", frameCounter)
        let framesDir = dir.appendingPathComponent("frames")
        let jpegURL   = framesDir.appendingPathComponent(filename)
        let metaURL   = framesDir.appendingPathComponent(
            filename.replacingOccurrences(of: ".jpg", with: ".json")
        )

        // Snapshot tags on main, then write to disk on a background queue.
        let imuTags   = getIMUTags?()   ?? ["motion_state": "stationary"]
        let audioTags = getAudioTags?() ?? ["noise_level": "quiet", "speech_detected": false]
        let ts = iso8601.string(from: capturedAt)
        let meta: [String: Any] = [
            "timestamp":        ts,
            "image_filename":   filename,
            "audio_tags":       audioTags,
            "imu_tags":         imuTags,
            "current_interval": currentInterval
        ]

        latestFrameFilename = filename
        latestFrameTimestamp = ts
        print("FramePipeline: saved \(filename) (\(totalFramesCaptured) total)")

        // Notify Layer 1.5 (BatchProcessor) — called on main thread before disk write.
        onFrameSaved?(jpegData, audioTags, imuTags, currentInterval)

        DispatchQueue.global(qos: .background).async {
            do { try jpegData.write(to: jpegURL) }
            catch { print("FramePipeline: failed to write \(filename): \(error)") }

            if let jsonData = try? JSONSerialization.data(withJSONObject: meta, options: .prettyPrinted) {
                try? jsonData.write(to: metaURL)
            }
        }
    }
}
