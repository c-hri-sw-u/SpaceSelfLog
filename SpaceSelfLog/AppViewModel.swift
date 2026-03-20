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
    @Published var serverAddress: String = "" // e.g. http://192.168.1.xxx:8080
    @Published var deviceName: String = UIDevice.current.name
    @Published var networkStatus: String = "" // simple IP status
    @Published var cameraError: String? = nil
    @Published var isCameraActive: Bool = false
    @Published var currentRotation: RotationAngle = .degrees0
    @Published var availableResolutions: [ResolutionPreset] = []
    @Published var selectedResolution: ResolutionPreset = .high
    @Published var batteryLevel: Float = 0.0
    @Published var batteryState: String = "Unknown"
    
    // MARK: - AI Analysis State
    @Published var isAIAnalysisEnabled: Bool = false
    @Published var aiAnalysisAutoMode: Bool = false // Toggle state: whether to auto-enable AI analysis during recording
    @Published var aiAnalysisInterval: TimeInterval = 30.0 // Default 30 seconds
    @Published var aiAnalysisPrompt: String = "What am I doing based on this image? Respond with a single English word with -ing."
    @Published var usingOpenRouter: Bool = true {
        didSet {
            UserDefaults.standard.set(usingOpenRouter, forKey: "UsingOpenRouter")
        }
    }
    @Published var openRouterAPIKey: String = "" {
        didSet {
            KeychainService.shared.set(value: openRouterAPIKey, key: "OpenRouterAPIKey")
            UserDefaults.standard.set(openRouterAPIKey, forKey: "OpenRouterAPIKey")
        }
    }
    @Published var geminiAPIKey: String = "" {
        didSet {
            KeychainService.shared.set(value: geminiAPIKey, key: "GeminiAPIKey")
            UserDefaults.standard.set(geminiAPIKey, forKey: "GeminiAPIKey")
        }
    }
    @Published var latestAnalysisResult: AnalysisResult?
    @Published var analysisHistory: [AnalysisResult] = []
    @Published var aiAnalysisError: String?
    @Published var experimentNumber: Int = 1 {
        didSet {
            UserDefaults.standard.set(experimentNumber, forKey: "ExperimentNumber")
        }
    }
    
    // MARK: - API Key Test State
    @Published var apiKeyTestStatus: String? = nil // "success", "failed", "testing", nil
    @Published var apiKeyTestMessage: String? = nil
    @Published var apiKeyTestTimestamp: Date? = nil
    
    // Used to track whether AI analysis needs to be started after camera is ready
    private var pendingAIAnalysisStart: Bool = false

    // MARK: - Managers
    private let camera = CameraManager()
    private let power = PowerManager()
    private lazy var aiAnalysisManager: AIAnalysisManager = {
        let manager = AIAnalysisManager()
        manager.setCameraManager(camera)
        return manager
    }()
    // Streaming throttle
    private var lastStreamSentAt: Date = .distantPast
    private var targetStreamFPS: Double = 15.0
    private lazy var server: StreamServer = {
        let s = StreamServer(port: 8080)
        s.onStart = { [weak self] in self?.startRecording() }
        s.onStop = { [weak self] in self?.stopRecording() }
        s.onPause = { [weak self] in self?.pauseRecording() }
        s.onResume = { [weak self] in self?.resumeRecording() }
        s.onSwitch = { [weak self] cam in self?.switchCamera(to: cam) }
        s.onRotate = { [weak self] in self?.rotateCamera() }
        s.onResolution = { [weak self] resolution in self?.switchResolution(to: resolution) }
        s.onAIAutoToggle = { [weak self] in self?.toggleAIAnalysisAutoMode() }
        s.onStatus = { [weak self] in
            guard let self = self else { return [:] }
            
            // Ensure we're on the main thread for accessing @Published properties
            if Thread.isMainThread {
                // Precompute values to simplify type checking
                let selectedCameraRaw = self.selectedCamera?.rawValue ?? "none"
                let availableResolutionsRaw = self.availableResolutions.map { $0.rawValue }
                let latestAnalysisResultDict = self.latestAnalysisResult?.toDictionary() ?? [:]
                let analysisHistoryDicts = self.analysisHistory.map { $0.toDictionary() }
                let hasKey = self.usingOpenRouter ? !self.openRouterAPIKey.isEmpty : !self.geminiAPIKey.isEmpty
                let apiKeyLengthVal = self.usingOpenRouter ? self.openRouterAPIKey.count : self.geminiAPIKey.count
                let apiKeyTestStatusVal = self.apiKeyTestStatus ?? ""
                let apiKeyTestMessageVal = self.apiKeyTestMessage ?? ""
                let apiKeyTestTimestampVal = self.apiKeyTestTimestamp?.timeIntervalSince1970 ?? 0
                let analysisStatsDict = self.aiAnalysisManager.statistics.toDictionary()
                
                return [
                    "isRecording": self.isRecording,
                    "isPaused": self.isPaused,
                    "duration": self.durationString,
                    "durationSeconds": self.secondsElapsed,
                    "recordingStartTime": self.recordingStartTime?.timeIntervalSince1970 ?? 0,
                    "deviceName": self.deviceName,
                    "serverAddress": self.serverAddress,
                    "networkStatus": self.networkStatus,
                    "selectedCamera": selectedCameraRaw,
                    "selectedResolution": self.selectedResolution.rawValue,
                    "availableResolutions": availableResolutionsRaw,
                    "currentRotation": self.currentRotation.rawValue,
                    "batteryLevel": self.batteryLevel,
                    "batteryState": self.batteryState,
                    "isAIAnalysisEnabled": self.isAIAnalysisEnabled,
                    "aiAnalysisAutoMode": self.aiAnalysisAutoMode,
                    "aiAnalysisInterval": self.aiAnalysisInterval,
                    "latestAnalysisResult": latestAnalysisResultDict,
                    "analysisHistory": analysisHistoryDicts,
                    "hasApiKey": hasKey,
                    "apiKeyLength": apiKeyLengthVal,
                    "currentPrompt": self.aiAnalysisPrompt,
                    "apiKeyTestStatus": apiKeyTestStatusVal,
                    "apiKeyTestMessage": apiKeyTestMessageVal,
                    "apiKeyTestTimestamp": apiKeyTestTimestampVal,
                    "analysisStatistics": analysisStatsDict,
                    "experimentNumber": self.experimentNumber,
                    "availableExperimentIds": ExperimentRegistry.ids
                ]
            } else {
                return DispatchQueue.main.sync {
                    // Precompute values to simplify type checking
                    let selectedCameraRaw = self.selectedCamera?.rawValue ?? "none"
                    let availableResolutionsRaw = self.availableResolutions.map { $0.rawValue }
                    let latestAnalysisResultDict = self.latestAnalysisResult?.toDictionary() ?? [:]
                    let analysisHistoryDicts = self.analysisHistory.map { $0.toDictionary() }
                    let hasKey = self.usingOpenRouter ? !self.openRouterAPIKey.isEmpty : !self.geminiAPIKey.isEmpty
                    let apiKeyLengthVal = self.usingOpenRouter ? self.openRouterAPIKey.count : self.geminiAPIKey.count
                    let apiKeyTestStatusVal = self.apiKeyTestStatus ?? ""
                    let apiKeyTestMessageVal = self.apiKeyTestMessage ?? ""
                    let apiKeyTestTimestampVal = self.apiKeyTestTimestamp?.timeIntervalSince1970 ?? 0
                    let analysisStatsDict = self.aiAnalysisManager.statistics.toDictionary()
                    
                    return [
                        "isRecording": self.isRecording,
                        "isPaused": self.isPaused,
                        "duration": self.durationString,
                        "durationSeconds": self.secondsElapsed,
                        "recordingStartTime": self.recordingStartTime?.timeIntervalSince1970 ?? 0,
                        "deviceName": self.deviceName,
                        "serverAddress": self.serverAddress,
                        "networkStatus": self.networkStatus,
                        "selectedCamera": selectedCameraRaw,
                        "selectedResolution": self.selectedResolution.rawValue,
                        "availableResolutions": availableResolutionsRaw,
                        "currentRotation": self.currentRotation.rawValue,
                        "batteryLevel": self.batteryLevel,
                        "batteryState": self.batteryState,
                        "isAIAnalysisEnabled": self.isAIAnalysisEnabled,
                        "aiAnalysisAutoMode": self.aiAnalysisAutoMode,
                        "aiAnalysisInterval": self.aiAnalysisInterval,
                        "latestAnalysisResult": latestAnalysisResultDict,
                        "analysisHistory": analysisHistoryDicts,
                        "hasApiKey": hasKey,
                        "apiKeyLength": apiKeyLengthVal,
                        "currentPrompt": self.aiAnalysisPrompt,
                        "apiKeyTestStatus": apiKeyTestStatusVal,
                        "apiKeyTestMessage": apiKeyTestMessageVal,
                        "apiKeyTestTimestamp": apiKeyTestTimestampVal,
                        "analysisStatistics": analysisStatsDict,
                        "experimentNumber": self.experimentNumber,
                        "availableExperimentIds": ExperimentRegistry.ids
                    ]
                }
            }
        }
        
        // Settings callbacks
        s.onTestAPIKey = { [weak self] in
            guard let self = self else { return (success: false, error: "AppViewModel not available") }
            
            // Choose provider based on toggle
            if self.usingOpenRouter {
                if self.openRouterAPIKey.isEmpty {
                    return (success: false, error: "No OpenRouter API key configured")
                }
            } else {
                if self.geminiAPIKey.isEmpty {
                    return (success: false, error: "No Gemini API key configured")
                }
            }
            
            // Use a semaphore to make this synchronous
            let semaphore = DispatchSemaphore(value: 0)
            var result: (success: Bool, error: String?) = (success: false, error: "Timeout")
            
            DispatchQueue.main.async {
                if self.usingOpenRouter {
                    self.testOpenRouterAPIKey(self.openRouterAPIKey) { success, error in
                        result = (success: success, error: error)
                        semaphore.signal()
                    }
                } else {
                    self.testGeminiAPIKey(self.geminiAPIKey) { success, error in
                        result = (success: success, error: error)
                        semaphore.signal()
                    }
                }
            }
            
            // Wait for up to 10 seconds
            _ = semaphore.wait(timeout: .now() + 10)
            return result
        }
        
        s.onUpdateInterval = { [weak self] interval in
            guard let self = self else { return false }
            
            DispatchQueue.main.async {
                self.updateAIAnalysisInterval(TimeInterval(interval))
            }
            return true
        }
        
        s.onUpdatePrompt = { [weak self] prompt in
            guard let self = self else { return false }
            
            DispatchQueue.main.async {
                self.updateAIAnalysisPrompt(prompt)
            }
            return true
        }
        
        s.onResetPrompt = { [weak self] in
            guard let self = self else { return nil }
            // Build context from recent formatted outputs for continuity-aware prompts
            let recentLabels = self.analysisHistory
                .map { $0.formattedOutput.activityLabel }
                .filter { !$0.isEmpty && $0 != "unknown" && !$0.contains("failed") }
            let context = ExperimentContext(previousLabels: recentLabels, includeCount: 5)
            let mode = ExperimentRegistry.mode(for: self.experimentNumber)
            let defaultPrompt = mode.defaultPrompt(context: context)
            DispatchQueue.main.async {
                self.updateAIAnalysisPrompt(defaultPrompt)
            }
            return defaultPrompt
        }
        s.onUpdateExperiment = { [weak self] number in
            guard let self = self else { return false }
            DispatchQueue.main.async {
                self.updateExperiment(number)
            }
            return true
        }
        return s
    }()

    private var timer: Timer?
    private var secondsElapsed: Int = 0
    private var recordingStartTime: Date?

    // MARK: - Init
    init() {
        self.availableCameras = camera.discoverCameras()
        
        // Load saved camera selection, fallback to first available
        let savedCamera = camera.getSelectedCamera()
        self.selectedCamera = availableCameras.contains(savedCamera) ? savedCamera : availableCameras.first
        
        // Load available resolutions and saved selection
        self.availableResolutions = camera.getAvailableResolutions()
        self.selectedResolution = camera.getSelectedResolution()
        
        // Load saved AI Analysis settings
        self.usingOpenRouter = UserDefaults.standard.bool(forKey: "UsingOpenRouter")
        self.openRouterAPIKey = KeychainService.shared.get(key: "OpenRouterAPIKey") ?? (UserDefaults.standard.string(forKey: "OpenRouterAPIKey") ?? "")
        self.geminiAPIKey = KeychainService.shared.get(key: "GeminiAPIKey") ?? (UserDefaults.standard.string(forKey: "GeminiAPIKey") ?? "")
        self.aiAnalysisAutoMode = UserDefaults.standard.bool(forKey: "AIAnalysisAutoMode")
        self.aiAnalysisInterval = UserDefaults.standard.double(forKey: "AnalysisInterval")
        if self.aiAnalysisInterval <= 0 {
            self.aiAnalysisInterval = 30.0
        }
        let exp = UserDefaults.standard.integer(forKey: "ExperimentNumber")
        self.experimentNumber = exp == 0 ? 1 : exp

        // Ensure prompt is aligned with the current experiment on app start
        // so that web UI reflects the actual analysis prompt without manual reset.
        self.updateExperiment(self.experimentNumber)
        
        // Setup camera callbacks
        camera.onFrame = { [weak self] data in
            guard let self = self else { return }
            let minInterval = 1.0 / self.targetStreamFPS
            let now = Date()
            if now.timeIntervalSince(self.lastStreamSentAt) >= minInterval {
                self.lastStreamSentAt = now
                self.server.broadcastJPEGFrame(data)
            }
        }
        
        camera.onError = { [weak self] error in
            DispatchQueue.main.async {
                self?.cameraError = error
                print("AppViewModel: Camera error - \(error)")
            }
        }
        
        camera.onSessionStateChanged = { [weak self] isActive in
            DispatchQueue.main.async {
                self?.isCameraActive = isActive
                if isActive {
                    self?.cameraError = nil // Clear error when session becomes active
                    
                    // If there's pending AI analysis to start, start it now
                    if self?.pendingAIAnalysisStart == true && self?.isCameraActive == true {
                        self?.pendingAIAnalysisStart = false
                        print("AppViewModel: Camera ready, starting AI analysis")
                        self?.startAIAnalysis()
                    }
                }
            }
        }
        
        camera.onRotationChanged = { [weak self] rotation in
            DispatchQueue.main.async {
                self?.currentRotation = rotation
            }
        }
        
        camera.onCameraChanged = { [weak self] camera in
            DispatchQueue.main.async {
                self?.selectedCamera = camera
            }
        }
        
        camera.onResolutionChanged = { [weak self] resolution in
            DispatchQueue.main.async {
                self?.selectedResolution = resolution
            }
        }
        
        // Initialize rotation state
        currentRotation = camera.getCurrentRotation()
        
        // Initialize battery state
        updateBatteryInfo()
        
        // Setup AI Analysis callbacks
        setupAIAnalysisCallbacks()
        
        updateNetworkStatus()
    }

    // MARK: - Server
    func startServerIfNeeded() {
        if !server.isRunning {
            server.start()
            let ip = IPAddress.localIPv4() ?? "0.0.0.0"
            serverAddress = "http://\(ip):\(server.port)"
            updateNetworkStatus()
        }
    }

    private func updateNetworkStatus() {
        let ip = IPAddress.localIPv4() ?? "Unknown IP"
        networkStatus = "Wi-Fi: \(ip)"
    }

    // MARK: - Recording Control
    func startRecording() {
        guard !isRecording, let selectedCamera else { return }
        
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            
            // Initialize new session
            self.aiAnalysisManager.initializeSession()
            
            self.camera.start(camera: selectedCamera)
            self.power.enterLowPowerMode()
            self.startTimer()
            self.isRecording = true
            self.isPaused = false
            
            // If AI analysis auto mode is enabled, set pending start flag
            if aiAnalysisAutoMode {
                if isCameraActive {
                    // Camera is already active, start AI analysis immediately
                    print("AppViewModel: Camera already active, starting AI analysis immediately")
                    startAIAnalysis()
                } else {
                    // Camera not ready yet, set pending start flag
                    print("AppViewModel: Camera not ready, setting AI analysis pending start flag")
                    pendingAIAnalysisStart = true
                }
            }
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
            
            // Clear pending AI analysis start flag
            pendingAIAnalysisStart = false
            
            // When stopping recording, if AI analysis is running, stop AI analysis
            if self.isAIAnalysisEnabled {
                self.stopAIAnalysis()
            }

            // Stop IMU logging and flush buffered IMU data to CSV
            self.aiAnalysisManager.finalizeSession()
        }
    }

    /// Pause current recording: stop camera and ticking, keep low power mode and session
    func pauseRecording() {
        guard isRecording, !isPaused else { return }
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            // Stop camera to save power during pause
            self.camera.stop()
            // Do NOT exit low power mode on pause
            self.pauseTimer()
            self.isPaused = true
            // Stop AI analysis if running
            if self.isAIAnalysisEnabled {
                self.stopAIAnalysis()
            }
        }
    }

    /// Resume current recording: restart camera and ticking, continue same session
    func resumeRecording() {
        guard isRecording, isPaused, let selectedCamera else { return }
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            // Restart camera
            self.camera.start(camera: selectedCamera)
            // Keep low power mode
            self.resumeTimer()
            self.isPaused = false
            // If AI analysis auto mode is enabled, set pending start or start immediately
            if self.aiAnalysisAutoMode {
                if self.isCameraActive {
                    print("AppViewModel: Resumed, camera active, starting AI analysis")
                    self.startAIAnalysis()
                } else {
                    print("AppViewModel: Resumed, camera not ready, pending AI analysis start")
                    self.pendingAIAnalysisStart = true
                }
            }
        }
    }

    func switchCamera(to cameraType: CameraType) {
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            self.selectedCamera = cameraType
            if self.isRecording {
                self.camera.switchCamera(to: cameraType)
            }
        }
    }
    
    func rotateCamera() {
        camera.rotateCamera()
    }
    
    func switchResolution(to resolution: ResolutionPreset) {
        camera.switchResolution(to: resolution)
    }

    // MARK: - Timer
    private func startTimer() {
        recordingStartTime = Date()
        secondsElapsed = 0
        durationString = format(secondsElapsed)
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            guard let self = self else { return }
            self.secondsElapsed += 1
            self.durationString = self.format(self.secondsElapsed)
            
            // Update battery info every 10 seconds to avoid excessive calls
            if self.secondsElapsed % 10 == 0 {
                self.updateBatteryInfo()
            }
        }
        RunLoop.main.add(timer!, forMode: .common)
    }

    private func stopTimer() {
        timer?.invalidate()
        timer = nil
        recordingStartTime = nil
    }

    /// Stop ticking without resetting start time (used for pause)
    private func pauseTimer() {
        timer?.invalidate()
        timer = nil
        // Keep recordingStartTime to preserve original start time
    }

    /// Resume ticking from current secondsElapsed (used for resume)
    private func resumeTimer() {
        durationString = format(secondsElapsed)
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            guard let self = self else { return }
            self.secondsElapsed += 1
            self.durationString = self.format(self.secondsElapsed)
            
            if self.secondsElapsed % 10 == 0 {
                self.updateBatteryInfo()
            }
        }
        if let t = timer {
            RunLoop.main.add(t, forMode: .common)
        }
    }

    private func format(_ seconds: Int) -> String {
        let h = seconds / 3600
        let m = (seconds % 3600) / 60
        let s = seconds % 60
        return String(format: "%02d:%02d:%02d", h, m, s)
    }
    
    // MARK: - Battery
    private func updateBatteryInfo() {
        let batteryInfo = power.getBatteryInfo()
        DispatchQueue.main.async {
            self.batteryLevel = batteryInfo.level
            self.batteryState = batteryInfo.state
        }
    }
    
    // MARK: - AI Analysis
    private func setupAIAnalysisCallbacks() {
        aiAnalysisManager.onAnalysisResult = { [weak self] result in
            DispatchQueue.main.async {
                self?.latestAnalysisResult = result
                self?.analysisHistory.append(result)
                self?.aiAnalysisError = nil
                
                // Keep history records within reasonable range (max 100 entries)
                if self?.analysisHistory.count ?? 0 > 100 {
                    self?.analysisHistory.removeFirst()
                }
            }
        }
        
        aiAnalysisManager.onError = { [weak self] error in
            DispatchQueue.main.async {
                self?.aiAnalysisError = error
                print("AppViewModel: AI analysis error - \(error)")
            }
        }
    }
    
    func toggleAIAnalysis() {
        if isAIAnalysisEnabled {
            stopAIAnalysis()
        } else {
            startAIAnalysis()
        }
    }
    
    func toggleAIAnalysisAutoMode() {
        DispatchQueue.main.async { [weak self] in
            self?.aiAnalysisAutoMode.toggle()
            UserDefaults.standard.set(self?.aiAnalysisAutoMode ?? false, forKey: "AIAnalysisAutoMode")
        }
    }
    
    func startAIAnalysis() {
        if usingOpenRouter {
            guard !openRouterAPIKey.isEmpty else {
                aiAnalysisError = "Please set OpenRouter API Key first"
                return
            }
        } else {
            guard !geminiAPIKey.isEmpty else {
                aiAnalysisError = "Please set Gemini API Key first"
                return
            }
        }
        
        aiAnalysisManager.updateConfiguration(
            apiKey: usingOpenRouter ? openRouterAPIKey : geminiAPIKey,
            prompt: aiAnalysisPrompt,
            interval: aiAnalysisInterval,
            usingOpenRouter: usingOpenRouter
        )
        
        aiAnalysisManager.startAnalysis()
        isAIAnalysisEnabled = true
        aiAnalysisError = nil
    }
    
    func stopAIAnalysis() {
        aiAnalysisManager.stopAnalysis()
        isAIAnalysisEnabled = false
    }
    
    func updateAIAnalysisInterval(_ interval: TimeInterval) {
        aiAnalysisInterval = interval
        // Persist regardless of analysis state so Settings reflects latest value
        UserDefaults.standard.set(interval, forKey: "AnalysisInterval")
        if isAIAnalysisEnabled {
            aiAnalysisManager.updateInterval(interval)
        }
    }
    
    func updateAIAnalysisPrompt(_ prompt: String) {
        aiAnalysisPrompt = prompt
        if isAIAnalysisEnabled {
            aiAnalysisManager.updateConfiguration(
                apiKey: usingOpenRouter ? openRouterAPIKey : geminiAPIKey,
                prompt: prompt,
                interval: aiAnalysisInterval,
                usingOpenRouter: usingOpenRouter
            )
        }
    }

    /// Update Experiment selection (dynamic), persist and inform AIAnalysisManager
    func updateExperiment(_ number: Int) {
        let minId = ExperimentRegistry.minId
        let maxId = ExperimentRegistry.maxId
        let clamped = max(minId, min(maxId, number))
        experimentNumber = clamped
        aiAnalysisManager.updateExperiment(clamped)
        // Reset prompt to the experiment's default (dynamic where applicable)
        let recentLabels = analysisHistory
            .map { $0.formattedOutput.activityLabel }
            .filter { !$0.isEmpty && $0 != "unknown" && !$0.contains("failed") }
        let context = ExperimentContext(previousLabels: recentLabels, includeCount: 5)
        let mode = ExperimentRegistry.mode(for: clamped)
        let newDefault = mode.defaultPrompt(context: context)
        updateAIAnalysisPrompt(newDefault)
    }
    
    func testGeminiAPIKey(_ apiKey: String, completion: @escaping (Bool, String?) -> Void) {
        // Set test status to in progress
        apiKeyTestStatus = "testing"
        apiKeyTestMessage = "Testing Gemini API Key..."
        apiKeyTestTimestamp = Date()
        
        let geminiService = GeminiAPIService()
        geminiService.testAPIKey(apiKey) { result in
            DispatchQueue.main.async {
                switch result {
                case .success:
                    self.apiKeyTestStatus = "success"
                    self.apiKeyTestMessage = "API Key is valid"
                    self.apiKeyTestTimestamp = Date()
                    completion(true, nil)
                case .failure(let error):
                    self.apiKeyTestStatus = "failed"
                    self.apiKeyTestMessage = error.localizedDescription
                    self.apiKeyTestTimestamp = Date()
                    completion(false, error.localizedDescription)
                }
            }
        }
    }

    func testOpenRouterAPIKey(_ apiKey: String, completion: @escaping (Bool, String?) -> Void) {
        apiKeyTestStatus = "testing"
        apiKeyTestMessage = "Testing OpenRouter API Key..."
        apiKeyTestTimestamp = Date()

        let orService = OpenRouterAPIService()
        orService.testAPIKey(apiKey, presetSlug: "space-self-log") { result in
            DispatchQueue.main.async {
                switch result {
                case .success:
                    self.apiKeyTestStatus = "success"
                    self.apiKeyTestMessage = "API Key is valid"
                    self.apiKeyTestTimestamp = Date()
                    completion(true, nil)
                case .failure(let error):
                    self.apiKeyTestStatus = "failed"
                    self.apiKeyTestMessage = error.localizedDescription
                    self.apiKeyTestTimestamp = Date()
                    completion(false, error.localizedDescription)
                }
            }
        }
    }
    
    // MARK: - Data Management Functions
    
    /// Export analysis data as JSON file
    func exportAnalysisData(completion: @escaping (Result<URL, Error>) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            if let url = self.aiAnalysisManager.exportAnalysisData() {
                DispatchQueue.main.async {
                    completion(.success(url))
                }
            } else {
                DispatchQueue.main.async {
                    completion(.failure(NSError(domain: "DataExport", code: 1, userInfo: [NSLocalizedDescriptionKey: "Failed to export analysis data"])))
                }
            }
        }
    }
    
    /// Export images archive
    func exportImagesArchive(completion: @escaping (Result<URL, Error>) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            if let url = self.aiAnalysisManager.exportImagesArchive() {
                DispatchQueue.main.async {
                    completion(.success(url))
                }
            } else {
                DispatchQueue.main.async {
                    completion(.failure(NSError(domain: "DataExport", code: 2, userInfo: [NSLocalizedDescriptionKey: "Failed to export images archive"])))
                }
            }
        }
    }
    
    /// Clear all analysis data
    func clearAllAnalysisData(completion: @escaping (Result<Void, Error>) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            self.aiAnalysisManager.clearAllData()
            DispatchQueue.main.async {
                // Clear UI state
                self.latestAnalysisResult = nil
                self.analysisHistory = []
                self.aiAnalysisError = nil
                completion(.success(()))
            }
        }
    }
    
    /// Get storage information
    func getStorageInfo() -> (analysisCount: Int, totalImageSize: String, totalDataSize: String) {
        let info = aiAnalysisManager.getStorageInfo()
        
        let analysisCount = info["resultsCount"] as? Int ?? 0
        let totalImageSizeBytes = info["totalImageSize"] as? Int64 ?? 0
        let totalSizeBytes = info["totalSize"] as? Int64 ?? 0
        
        // Format file size
        let formatter = ByteCountFormatter()
        formatter.allowedUnits = [.useKB, .useMB, .useGB]
        formatter.countStyle = .file
        
        let totalImageSize = formatter.string(fromByteCount: totalImageSizeBytes)
        let totalDataSize = formatter.string(fromByteCount: totalSizeBytes)
        
        return (analysisCount: analysisCount, totalImageSize: totalImageSize, totalDataSize: totalDataSize)
    }
    
    /// Get current session information
    func getCurrentSessionInfo() -> (sessionId: String, sessionStartTime: Date, analysisCount: Int, totalImageSize: String, totalDataSize: String, analysisInterval: TimeInterval) {
        let info = aiAnalysisManager.getStorageInfo()
        
        let sessionId = info["sessionId"] as? String ?? "Unknown"
        let sessionStartTime = info["sessionStartTime"] as? Date ?? Date()
        let analysisCount = info["resultsCount"] as? Int ?? 0
        let totalImageSizeBytes = info["totalImageSize"] as? Int64 ?? 0
        let totalSizeBytes = info["totalSize"] as? Int64 ?? 0
        
        // Format file size
        let formatter = ByteCountFormatter()
        formatter.allowedUnits = [.useKB, .useMB, .useGB]
        formatter.countStyle = .file
        
        let totalImageSize = formatter.string(fromByteCount: totalImageSizeBytes)
        let totalDataSize = formatter.string(fromByteCount: totalSizeBytes)
        
        return (sessionId: sessionId, sessionStartTime: sessionStartTime, analysisCount: analysisCount, totalImageSize: totalImageSize, totalDataSize: totalDataSize, analysisInterval: aiAnalysisInterval)
    }
    
    // MARK: - Historical Sessions Management
    
    /// Get historical sessions list
    func getHistoricalSessions() -> [SessionInfo] {
        return aiAnalysisManager.getHistoricalSessions()
    }
    
    /// Delete specified historical session
    func deleteHistoricalSession(sessionId: String, completion: @escaping (Bool) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let self = self else {
                DispatchQueue.main.async {
                    completion(false)
                }
                return
            }
            
            let success = self.aiAnalysisManager.deleteHistoricalSession(sessionId: sessionId)
            
            DispatchQueue.main.async {
                completion(success)
            }
        }
    }
}
