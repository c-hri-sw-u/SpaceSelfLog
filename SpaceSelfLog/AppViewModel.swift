import Foundation
import Combine
import UIKit

final class AppViewModel: ObservableObject {

    // MARK: - Published UI State
    @Published var availableCameras: [CameraType] = []
    @Published var selectedCamera: CameraType? = nil
    @Published var isRecording: Bool = false
    @Published var isPaused: Bool = false
    @Published var durationString: String = "00:00:00"
    @Published var serverAddress: String = ""
    @Published var deviceName: String = UIDevice.current.name
    @Published var networkStatus: String = ""
    @Published var cameraError: String? = nil
    @Published var isCameraActive: Bool = false
    @Published var currentRotation: RotationAngle = .degrees0
    @Published var availableResolutions: [ResolutionPreset] = []
    @Published var selectedResolution: ResolutionPreset = .high
    @Published var batteryLevel: Float = 0.0
    @Published var batteryState: String = "Unknown"
    private(set) var storageUsedMB: Double = 0.0

    // MARK: - IMU Motion State
    @Published var motionState: MotionState = .stationary

    // MARK: - Pipeline Config
    @Published var captureMinInterval: Int = 3 {
        didSet { UserDefaults.standard.set(captureMinInterval, forKey: "CaptureMinInterval") }
    }
    @Published var captureMaxInterval: Int = 20 {
        didSet { UserDefaults.standard.set(captureMaxInterval, forKey: "CaptureMaxInterval") }
    }
    @Published var sustainedMotionThreshold: Int = 6 {
        didSet { UserDefaults.standard.set(sustainedMotionThreshold, forKey: "SustainedMotionThreshold") }
    }
    @Published var firstBatchWindow: Int = 120 {
        didSet {
            UserDefaults.standard.set(firstBatchWindow, forKey: "FirstBatchWindow")
            batchProcessor.firstBatchWindowSeconds = Double(firstBatchWindow)
        }
    }
    @Published var batchMaxWindow: Int = 600 {
        didSet {
            UserDefaults.standard.set(batchMaxWindow, forKey: "BatchMaxWindow")
            batchProcessor.maxWindowSeconds = Double(batchMaxWindow)
        }
    }
    @Published var ssimThreshold: Double = 0.85 {
        didSet {
            UserDefaults.standard.set(ssimThreshold, forKey: "SSIMThreshold")
            batchProcessor.ssimBoundaryThreshold = Float(ssimThreshold)
        }
    }
    @Published var ssimDedupThreshold: Double = 0.92 {
        didSet {
            UserDefaults.standard.set(ssimDedupThreshold, forKey: "SSIMDedupThreshold")
            batchProcessor.ssimDedupThreshold = Float(ssimDedupThreshold)
        }
    }
    @Published var kDensityPerMin: Double = 1.0 {
        didSet {
            UserDefaults.standard.set(kDensityPerMin, forKey: "KDensityPerMin")
            batchProcessor.kDensityPerMin = kDensityPerMin
        }
    }
    @Published var kMin: Int = 2 {
        didSet {
            UserDefaults.standard.set(kMin, forKey: "KMin")
            batchProcessor.kMin = kMin
        }
    }
    @Published var kMax: Int = 12 {
        didSet {
            UserDefaults.standard.set(kMax, forKey: "KMax")
            batchProcessor.kMax = kMax
        }
    }
    @Published var scoreThreshold: Double = 0.50 {
        didSet {
            UserDefaults.standard.set(scoreThreshold, forKey: "ScoreThreshold")
            batchProcessor.scoreThreshold = Float(scoreThreshold)
        }
    }
    @Published var outboxEndpoint: String = "" {
        didSet {
            UserDefaults.standard.set(outboxEndpoint, forKey: "OutboxEndpoint")
            outboxManager.uploadEndpoint = outboxEndpoint.isEmpty ? nil : URL(string: outboxEndpoint)
        }
    }
    @Published var rampRatio: Double = 1.67 {
        didSet { UserDefaults.standard.set(rampRatio, forKey: "RampRatio") }
    }
    @Published var vadSensitivity: String = "Med" {
        didSet {
            UserDefaults.standard.set(vadSensitivity, forKey: "VADSensitivity")
            audioManager.vadSensitivity = vadSensitivity
        }
    }
    @Published var transcriptionEnabled: Bool = false {
        didSet {
            UserDefaults.standard.set(transcriptionEnabled, forKey: "TranscriptionEnabled")
            audioManager.transcriptionEnabled = transcriptionEnabled
        }
    }

    // MARK: - Managers
    private let camera = CameraManager()
    private let power = PowerManager()
    private let imuManager = IMUManager()
    private let audioManager = AudioManager()
    private let framePipeline = FramePipeline()
    private let sessionManager = AIAnalysisManager()
    private let batchProcessor = BatchProcessor()
    private let outboxManager = OutboxManager()

    // Streaming throttle
    private var lastStreamSentAt: Date = .distantPast
    private var targetStreamFPS: Double = 15.0

    private lazy var server: StreamServer = {
        let s = StreamServer(port: 8080)
        s.onStart = { [weak self] in self?.startRecording() }
        s.onStop  = { [weak self] in self?.stopRecording() }
        s.onPause  = { [weak self] in self?.pauseRecording() }
        s.onResume = { [weak self] in self?.resumeRecording() }
        s.onSwitch = { [weak self] cam in self?.switchCamera(to: cam) }
        s.onRotate = { [weak self] in self?.rotateCamera() }
        s.onResolution = { [weak self] res in self?.switchResolution(to: res) }
        s.onStatus = { [weak self] in
            guard let self = self else { return [:] }
            let build: () -> [String: Any] = {
                return [
                    "isRecording": self.isRecording,
                    "isPaused": self.isPaused,
                    "duration": self.durationString,
                    "durationSeconds": self.secondsElapsed,
                    "recordingStartTime": self.recordingStartTime?.timeIntervalSince1970 ?? 0,
                    "deviceName": self.deviceName,
                    "serverAddress": self.serverAddress,
                    "networkStatus": self.networkStatus,
                    "selectedCamera": self.selectedCamera?.rawValue ?? "none",
                    "selectedResolution": self.selectedResolution.rawValue,
                    "availableResolutions": self.availableResolutions.map { $0.rawValue },
                    "currentRotation": self.currentRotation.rawValue,
                    "batteryLevel": self.batteryLevel,
                    "batteryState": self.batteryState,
                    "imu_tags": self.imuManager.imuTags,
                    "varianceLowThreshold": self.imuManager.varianceLowThreshold,
                    "varianceHighThreshold": self.imuManager.varianceHighThreshold,
                    "vadState": self.audioManager.isSpeechActive ? "speech" : "quiet",
                    "vadRMS": self.audioManager.latestRMS,
                    "vadThreshold": self.audioManager.vadThreshold,
                    "noiseLevel": self.audioManager.currentNoiseLevel.rawValue,
                    "noiseDB": self.audioManager.smoothedNoiseDB,
                    "noiseQuietDB": self.audioManager.quietThresholdDB,
                    "noiseLoudDB": self.audioManager.loudThresholdDB,
                    "captureInterval": self.framePipeline.currentInterval,
                    "captureMinInterval": self.captureMinInterval,
                    "captureMaxInterval": self.captureMaxInterval,
                    "rampRatio": self.rampRatio,
                    "vadSensitivity": self.vadSensitivity,
                    "transcriptionEnabled": self.transcriptionEnabled,
                    "sustainedMotionThreshold": self.sustainedMotionThreshold,
                    "firstBatchWindow": self.firstBatchWindow,
                    "batchMaxWindow": self.batchMaxWindow,
                    "ssimThreshold": self.ssimThreshold,
                    "ssimDedupThreshold": self.ssimDedupThreshold,
                    "kDensityPerMin": self.kDensityPerMin,
                    "kMin": self.kMin,
                    "kMax": self.kMax,
                    "scoreThreshold": self.scoreThreshold,
                    "totalFramesCaptured": self.framePipeline.totalFramesCaptured,
                    "latestFrameFilename": self.framePipeline.latestFrameFilename as Any,
                    "lastFrameTimestamp": self.framePipeline.latestFrameTimestamp as Any,
                    "batchBufferCount": self.batchProcessor.pendingFrameCount,
                    "totalBatchesProcessed": self.batchProcessor.totalBatchesProcessed,
                    "storageUsedMB": self.storageUsedMB,
                    "batchLastOutputCount": self.batchProcessor.lastBatchOutputCount,
                    "lastBatchTime": self.batchProcessor.lastBatchTime?.timeIntervalSince1970 as Any,
                    "lastBatchTrigger": self.batchProcessor.lastBatchTrigger,
                    "outboxQueueSize": self.outboxManager.queueSize,
                    "outboxLastUploadStatus": self.outboxManager.lastUploadStatus,
                    "outboxFailureCount": self.outboxManager.failureCount,
                    "outboxEndpoint": self.outboxEndpoint,
                    "latestBatchOutput": self.latestBatchOutput,
                    "batchHistory": self.batchResultHistory,
                    "lastSSIMComparison": self.batchProcessor.lastSSIMDebugDict as Any
                ]
            }
            return Thread.isMainThread ? build() : DispatchQueue.main.sync { build() }
        }
        s.onUpdateCaptureConfig = { [weak self] minInterval, maxInterval, rampRatio in
            guard let self = self else { return false }
            DispatchQueue.main.async {
                self.captureMinInterval = minInterval
                self.captureMaxInterval = maxInterval
                self.rampRatio = rampRatio
                self.framePipeline.updateIntervals(minInterval: minInterval, maxInterval: maxInterval, rampRatio: rampRatio)
            }
            return true
        }
        s.onUpdateAudioConfig = { [weak self] vadSensitivity, transcriptionEnabled, noiseQuietDB, noiseLoudDB in
            guard let self = self else { return false }
            DispatchQueue.main.async {
                self.vadSensitivity = vadSensitivity
                self.transcriptionEnabled = transcriptionEnabled
                self.audioManager.quietThresholdDB = Float(noiseQuietDB)
                self.audioManager.loudThresholdDB  = Float(noiseLoudDB)
            }
            return true
        }
        s.onUpdateIMUConfig = { [weak self] threshold, varianceLow, varianceHigh in
            guard let self = self else { return false }
            DispatchQueue.main.async {
                self.sustainedMotionThreshold = threshold
                self.imuManager.sustainedMotionThresholdSeconds = Double(threshold)
                self.imuManager.varianceLowThreshold  = varianceLow
                self.imuManager.varianceHighThreshold = varianceHigh
                UserDefaults.standard.set(varianceLow,  forKey: "VarianceLowThreshold")
                UserDefaults.standard.set(varianceHigh, forKey: "VarianceHighThreshold")
            }
            return true
        }
        s.onUpdateBatchConfig = { [weak self] firstBatchWindow, maxWindow, ssimThreshold, ssimDedupThreshold, kDensityPerMin, kMin, kMax, scoreThreshold in
            guard let self else { return false }
            DispatchQueue.main.async {
                self.firstBatchWindow    = firstBatchWindow
                self.batchMaxWindow      = maxWindow
                self.ssimThreshold       = ssimThreshold
                self.ssimDedupThreshold  = ssimDedupThreshold
                self.kDensityPerMin      = kDensityPerMin
                self.kMin                = kMin
                self.kMax                = kMax
                self.scoreThreshold      = scoreThreshold
            }
            return true
        }
        s.onUpdateOutboxConfig = { [weak self] endpoint in
            guard let self else { return false }
            DispatchQueue.main.async { self.outboxEndpoint = endpoint }
            return true
        }
        return s
    }()

    private func setupOutboxCallback() {
        outboxManager.onSummaryReceived = { [weak self] summary, time, frameCount in
            guard let self else { return }
            self.latestBatchOutput = summary
            let entry: [String: Any] = [
                "time":      time.timeIntervalSince1970 * 1000,
                "output":    summary,
                "keyFrames": frameCount,
                "trigger":   "upload"
            ]
            self.batchResultHistory.insert(entry, at: 0)
            if self.batchResultHistory.count > 20 {
                self.batchResultHistory.removeLast()
            }
        }
    }

    private var timer: Timer?
    private var secondsElapsed: Int = 0
    private var recordingStartTime: Date?

    // MARK: - Init
    init() {
        availableCameras = camera.discoverCameras()
        let saved = camera.getSelectedCamera()
        selectedCamera = availableCameras.contains(saved) ? saved : availableCameras.first

        availableResolutions = camera.getAvailableResolutions()
        selectedResolution = camera.getSelectedResolution()

        // Load persisted pipeline config
        let minI = UserDefaults.standard.integer(forKey: "CaptureMinInterval")
        captureMinInterval = minI > 0 ? minI : 3
        let maxI = UserDefaults.standard.integer(forKey: "CaptureMaxInterval")
        captureMaxInterval = maxI > 0 ? maxI : 20
        let thresh = UserDefaults.standard.integer(forKey: "SustainedMotionThreshold")
        sustainedMotionThreshold = thresh > 0 ? thresh : 6
        let fbw = UserDefaults.standard.integer(forKey: "FirstBatchWindow")
        firstBatchWindow = fbw > 0 ? fbw : 120
        let bw = UserDefaults.standard.integer(forKey: "BatchMaxWindow")
        batchMaxWindow = bw > 0 ? bw : 600
        let ssim = UserDefaults.standard.double(forKey: "SSIMThreshold")
        ssimThreshold = ssim > 0 ? ssim : 0.85
        let ssimDedup = UserDefaults.standard.double(forKey: "SSIMDedupThreshold")
        ssimDedupThreshold = ssimDedup > 0 ? ssimDedup : 0.92
        let kd = UserDefaults.standard.double(forKey: "KDensityPerMin")
        kDensityPerMin = kd > 0 ? kd : 1.0
        let kMnVal = UserDefaults.standard.integer(forKey: "KMin")
        kMin = kMnVal > 0 ? kMnVal : 2
        let kMxVal = UserDefaults.standard.integer(forKey: "KMax")
        kMax = kMxVal > 0 ? kMxVal : 12
        let st = UserDefaults.standard.double(forKey: "ScoreThreshold")
        scoreThreshold = st > 0 ? st : 0.50
        let rr = UserDefaults.standard.double(forKey: "RampRatio")
        rampRatio = rr > 0 ? rr : 1.67
        let ep = UserDefaults.standard.string(forKey: "OutboxEndpoint") ?? ""
        outboxEndpoint = ep

        // Sync batch processor config from loaded values
        batchProcessor.firstBatchWindowSeconds = Double(firstBatchWindow)
        batchProcessor.maxWindowSeconds        = Double(batchMaxWindow)
        batchProcessor.ssimBoundaryThreshold   = Float(ssimThreshold)
        batchProcessor.ssimDedupThreshold      = Float(ssimDedupThreshold)
        batchProcessor.kDensityPerMin          = kDensityPerMin
        batchProcessor.kMin                    = kMin
        batchProcessor.kMax                    = kMax
        batchProcessor.scoreThreshold          = Float(scoreThreshold)
        outboxManager.uploadEndpoint           = ep.isEmpty ? nil : URL(string: ep)
        setupOutboxCallback()

        // Camera callbacks
        camera.onFrame = { [weak self] data in
            guard let self = self else { return }
            let now = Date()
            if now.timeIntervalSince(self.lastStreamSentAt) >= 1.0 / self.targetStreamFPS {
                self.lastStreamSentAt = now
                self.server.broadcastJPEGFrame(data)
            }
        }
        camera.onError = { [weak self] err in
            DispatchQueue.main.async { self?.cameraError = err }
        }
        camera.onSessionStateChanged = { [weak self] active in
            DispatchQueue.main.async {
                self?.isCameraActive = active
                if active { self?.cameraError = nil }
            }
        }
        camera.onRotationChanged = { [weak self] r in
            DispatchQueue.main.async { self?.currentRotation = r }
        }
        camera.onCameraChanged = { [weak self] c in
            DispatchQueue.main.async { self?.selectedCamera = c }
        }
        camera.onResolutionChanged = { [weak self] r in
            DispatchQueue.main.async { self?.selectedResolution = r }
        }

        currentRotation = camera.getCurrentRotation()
        updateBatteryInfo()

        // IMU
        imuManager.onMotionStateChanged = { [weak self] state in
            self?.motionState = state
            self?.framePipeline.handleMotionStateChange(state)
        }
        imuManager.sustainedMotionThresholdSeconds = Double(sustainedMotionThreshold)
        let vl = UserDefaults.standard.double(forKey: "VarianceLowThreshold")
        if vl > 0 { imuManager.varianceLowThreshold = vl }
        let vh = UserDefaults.standard.double(forKey: "VarianceHighThreshold")
        if vh > 0 { imuManager.varianceHighThreshold = vh }

        // FramePipeline
        framePipeline.capturePhoto = { [weak self] completion in
            self?.camera.capturePhoto(completion: completion)
        }
        framePipeline.getIMUTags = { [weak self] in
            self?.imuManager.imuTags ?? ["motion_state": "stationary"]
        }
        framePipeline.getAudioTags = { [weak self] in
            self?.audioManager.audioTags ?? ["noise_level": "quiet", "speech_detected": false]
        }

        // AudioManager — load persisted config and wire VAD triggers into FramePipeline
        let savedVAD = UserDefaults.standard.string(forKey: "VADSensitivity") ?? "Med"
        vadSensitivity = savedVAD
        audioManager.vadSensitivity = savedVAD
        transcriptionEnabled = UserDefaults.standard.bool(forKey: "TranscriptionEnabled")
        audioManager.transcriptionEnabled = transcriptionEnabled

        audioManager.onSpeechOnset = { [weak self] in
            self?.framePipeline.handleVADStateChange(speechDetected: true)
        }
        audioManager.onSpeechOffset = { [weak self] in
            self?.framePipeline.handleVADStateChange(speechDetected: false)
        }

        // Layer 1 → Layer 1.5: feed every saved frame into the batch processor.
        framePipeline.onFrameSaved = { [weak self] jpegData, audioTags, imuTags, interval in
            self?.batchProcessor.ingest(
                jpegData: jpegData,
                audioTags: audioTags,
                imuTags: imuTags,
                currentInterval: interval
            )
        }

        // Layer 1.5 → Outbox: enqueue processed batches for upload.
        batchProcessor.onBatchReady = { [weak self] batch in
            self?.outboxManager.enqueue(batch: batch)
        }

        updateNetworkStatus()
    }

    // MARK: - Outbox / Batch passthrough (read-only, for UI)

    var outboxQueueSize: Int        { outboxManager.queueSize }
    var outboxUploadStatus: String  { outboxManager.lastUploadStatus }
    var outboxFailureCount: Int     { outboxManager.failureCount }
    var batchPendingFrames: Int     { batchProcessor.pendingFrameCount }
    var batchTotalProcessed: Int    { batchProcessor.totalBatchesProcessed }

    // MARK: - Inference results (from Mac)
    private var latestBatchOutput: String = ""
    private var batchResultHistory: [[String: Any]] = []  // max 20 entries

    // MARK: - Server
    func startServerIfNeeded() {
        guard !server.isRunning else { return }
        server.start()
        let ip = IPAddress.localIPv4() ?? "0.0.0.0"
        serverAddress = "http://\(ip):\(server.port)"
        updateNetworkStatus()
    }

    private func updateNetworkStatus() {
        networkStatus = "Wi-Fi: \(IPAddress.localIPv4() ?? "Unknown IP")"
    }

    // MARK: - Recording Control

    func startRecording() {
        guard !isRecording, let selectedCamera else { return }
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            self.sessionManager.initializeSession()
            self.camera.start(camera: selectedCamera)
            self.power.enterLowPowerMode()
            self.startTimer()
            self.isRecording = true
            self.isPaused = false

            let sessionDir = self.sessionManager.sessionDirectory
            let dataDir    = self.sessionManager.dataDirectory
            self.imuManager.start(dataDirectory: dataDir)
            self.audioManager.start(dataDirectory: dataDir)
            self.framePipeline.start(
                sessionDirectory: sessionDir,
                minInterval: self.captureMinInterval,
                maxInterval: self.captureMaxInterval,
                rampRatio: self.rampRatio
            )
            self.batchProcessor.start(sessionDirectory: sessionDir)
            self.outboxManager.start(sessionDirectory: sessionDir)
        }
    }

    func stopRecording() {
        guard isRecording else { return }
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            self.camera.stop()
            self.power.exitLowPowerMode()
            self.stopTimer()
            self.isRecording = false
            self.isPaused = false
            self.imuManager.stop()
            self.audioManager.stop()
            self.framePipeline.stop()
            self.batchProcessor.flush()
            self.outboxManager.stop()
            self.sessionManager.finalizeSession()
        }
    }

    func pauseRecording() {
        guard isRecording, !isPaused else { return }
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            self.camera.stop()
            self.pauseTimer()
            self.isPaused = true
            self.imuManager.stop()
            self.audioManager.stop()
            self.framePipeline.stop()
            self.batchProcessor.flush()
            self.outboxManager.stop()
        }
    }

    func resumeRecording() {
        guard isRecording, isPaused, let selectedCamera else { return }
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            self.camera.start(camera: selectedCamera)
            self.resumeTimer()
            self.isPaused = false
            let sessionDir = self.sessionManager.sessionDirectory
            let dataDir    = self.sessionManager.dataDirectory
            self.imuManager.start(dataDirectory: dataDir)
            self.audioManager.start(dataDirectory: dataDir)
            self.framePipeline.start(
                sessionDirectory: sessionDir,
                minInterval: self.captureMinInterval,
                maxInterval: self.captureMaxInterval,
                rampRatio: self.rampRatio
            )
            self.batchProcessor.start(sessionDirectory: sessionDir)
            self.outboxManager.start(sessionDirectory: sessionDir)
        }
    }

    func switchCamera(to cameraType: CameraType) {
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            self.selectedCamera = cameraType
            if self.isRecording { self.camera.switchCamera(to: cameraType) }
        }
    }

    func rotateCamera() { camera.rotateCamera() }
    func switchResolution(to resolution: ResolutionPreset) { camera.switchResolution(to: resolution) }

    // MARK: - Timer

    private func startTimer() {
        recordingStartTime = Date()
        secondsElapsed = 0
        durationString = format(0)
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            guard let self = self else { return }
            self.secondsElapsed += 1
            self.durationString = self.format(self.secondsElapsed)
            if self.secondsElapsed % 10 == 0 { self.updateBatteryInfo() }
            if self.secondsElapsed % 30 == 0 { self.updateStorageInfo() }
        }
        RunLoop.main.add(timer!, forMode: .common)
    }

    private func stopTimer() { timer?.invalidate(); timer = nil; recordingStartTime = nil }
    private func pauseTimer() { timer?.invalidate(); timer = nil }

    private func resumeTimer() {
        durationString = format(secondsElapsed)
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            guard let self = self else { return }
            self.secondsElapsed += 1
            self.durationString = self.format(self.secondsElapsed)
            if self.secondsElapsed % 10 == 0 { self.updateBatteryInfo() }
            if self.secondsElapsed % 30 == 0 { self.updateStorageInfo() }
        }
        if let t = timer { RunLoop.main.add(t, forMode: .common) }
    }

    private func format(_ seconds: Int) -> String {
        String(format: "%02d:%02d:%02d", seconds / 3600, (seconds % 3600) / 60, seconds % 60)
    }

    // MARK: - Battery

    private func updateStorageInfo() {
        DispatchQueue.global(qos: .utility).async { [weak self] in
            guard let self else { return }
            let info = self.sessionManager.getStorageInfo()
            let bytes = info["totalDataSize"] as? Int64 ?? 0
            let mb = Double(bytes) / 1_000_000.0
            DispatchQueue.main.async { self.storageUsedMB = mb }
        }
    }

    private func updateBatteryInfo() {
        let info = power.getBatteryInfo()
        DispatchQueue.main.async {
            self.batteryLevel = info.level
            self.batteryState = info.state
        }
    }

    // MARK: - Data Management

    func getCurrentSessionInfo() -> (sessionId: String, sessionStartTime: Date, frameCount: Int, totalFrameSize: String, totalDataSize: String) {
        let info = sessionManager.getStorageInfo()
        let sessionId        = info["sessionId"] as? String ?? "Unknown"
        let startTime        = info["sessionStartTime"] as? Date ?? Date()
        let frameCount       = info["frameCount"] as? Int ?? 0
        let frameSizeBytes   = info["totalFrameSize"] as? Int64 ?? 0
        let totalSizeBytes   = info["totalDataSize"] as? Int64 ?? 0
        let fmt = ByteCountFormatter()
        fmt.allowedUnits = [.useKB, .useMB, .useGB]
        fmt.countStyle = .file
        return (sessionId, startTime, frameCount, fmt.string(fromByteCount: frameSizeBytes), fmt.string(fromByteCount: totalSizeBytes))
    }

    func getHistoricalSessions() -> [SessionInfo] {
        sessionManager.getHistoricalSessions()
    }

    func deleteHistoricalSession(sessionId: String, completion: @escaping (Bool) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let ok = self?.sessionManager.deleteHistoricalSession(sessionId: sessionId) ?? false
            DispatchQueue.main.async { completion(ok) }
        }
    }

    func clearSessionData(completion: @escaping (Result<Void, Error>) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            self.sessionManager.clearAllData()
            DispatchQueue.main.async { completion(.success(())) }
        }
    }
}
