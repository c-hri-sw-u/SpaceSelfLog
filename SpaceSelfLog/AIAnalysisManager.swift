import Foundation
import UIKit
import AVFoundation
import Combine

// MARK: - Data Models
struct AnalysisResult: Codable {
    let id: UUID
    let captureTime: Date      // Capture time
    let responseTime: Date     // AI response time
    let imagePath: String
    let modelOutput: String
    let formattedOutput: FormattedOutput

    enum CodingKeys: String, CodingKey {
        case id, captureTime, responseTime, imagePath, modelOutput, formattedOutput
    }
    
    // Inference time (milliseconds)
    var inferenceTimeMs: Double {
        return responseTime.timeIntervalSince(captureTime) * 1000
    }
    
    // Whether it's a successful analysis result
    var isSuccess: Bool {
        let label = formattedOutput.activityLabel.lowercased()
        return !label.contains("failed") && label != "unknown"
    }
    
    init(imagePath: String, modelOutput: String, formattedOutput: FormattedOutput, captureTime: Date) {
        self.id = UUID()
        self.captureTime = captureTime
        self.responseTime = Date()  // AI response time is current time
        self.imagePath = imagePath
        self.modelOutput = modelOutput
        self.formattedOutput = formattedOutput
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(UUID.self, forKey: .id)
        captureTime = try container.decode(Date.self, forKey: .captureTime)
        responseTime = try container.decode(Date.self, forKey: .responseTime)
        imagePath = try container.decode(String.self, forKey: .imagePath)
        modelOutput = try container.decode(String.self, forKey: .modelOutput)
        if let obj = try? container.decode(FormattedOutput.self, forKey: .formattedOutput) {
            formattedOutput = obj
        } else if let str = try? container.decode(String.self, forKey: .formattedOutput) {
            formattedOutput = FormattedOutput(activityLabel: str)
        } else {
            formattedOutput = FormattedOutput(activityLabel: "unknown")
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(id, forKey: .id)
        try container.encode(captureTime, forKey: .captureTime)
        try container.encode(responseTime, forKey: .responseTime)
        try container.encode(imagePath, forKey: .imagePath)
        try container.encode(modelOutput, forKey: .modelOutput)
        try container.encode(formattedOutput, forKey: .formattedOutput)
    }
    
    func toDictionary() -> [String: Any] {
        var formatted: [String: Any] = ["activityLabel": formattedOutput.activityLabel]
        // Prefer sanitized fields from formattedOutput
        if let loc = formattedOutput.location { formatted["location"] = loc }
        if let hands = formattedOutput.handsInTheView { formatted["handsInTheView"] = hands }
        if let objs = formattedOutput.objects { formatted["objects"] = objs }

        // Fill missing fields by parsing raw modelOutput as a fallback
        if formatted["location"] == nil || formatted["handsInTheView"] == nil || formatted["objects"] == nil {
            if let data = modelOutput.data(using: .utf8),
               let obj = try? JSONSerialization.jsonObject(with: data, options: []) as? [String: Any] {
                if formatted["location"] == nil, let loc = obj["location"] as? String {
                    formatted["location"] = loc
                }
                if formatted["handsInTheView"] == nil, let hands = obj["handsInTheView"] as? Bool {
                    formatted["handsInTheView"] = hands
                }
                if formatted["objects"] == nil, let objectsAny = obj["objects"] as? [Any] {
                    formatted["objects"] = objectsAny.compactMap { $0 as? String }
                }
            }
        }

        return [
            "id": id.uuidString,
            "captureTime": ISO8601DateFormatter().string(from: captureTime),
            "responseTime": ISO8601DateFormatter().string(from: responseTime),
            "inferenceTimeMs": inferenceTimeMs,
            "isSuccess": isSuccess,
            "imagePath": imagePath,
            "modelOutput": modelOutput,
            "formattedOutput": formatted
        ]
    }
}

// MARK: - Statistics Manager
class AnalysisStatistics: ObservableObject {
    @Published var totalInferenceTime: Double = 0.0  // Total inference time (milliseconds)
    @Published var successCount: Int = 0             // Success count
    @Published var failureCount: Int = 0             // Failure count
    
    // Average inference time (milliseconds)
    var averageInferenceTime: Double {
        return successCount > 0 ? totalInferenceTime / Double(successCount) : 0.0
    }
    
    // Success rate (percentage)
    var successRate: Double {
        let total = successCount + failureCount
        return total > 0 ? Double(successCount) / Double(total) * 100.0 : 0.0
    }
    
    func addResult(_ result: AnalysisResult) {
        if result.isSuccess {
            successCount += 1
            totalInferenceTime += result.inferenceTimeMs
        } else {
            failureCount += 1
        }
        
        // Save to UserDefaults
        saveToUserDefaults()
    }
    
    func reset() {
        totalInferenceTime = 0.0
        successCount = 0
        failureCount = 0
        saveToUserDefaults()
    }
    
    private func saveToUserDefaults() {
        UserDefaults.standard.set(totalInferenceTime, forKey: "TotalInferenceTime")
        UserDefaults.standard.set(successCount, forKey: "SuccessCount")
        UserDefaults.standard.set(failureCount, forKey: "FailureCount")
    }
    
    func loadFromUserDefaults() {
        totalInferenceTime = UserDefaults.standard.double(forKey: "TotalInferenceTime")
        successCount = UserDefaults.standard.integer(forKey: "SuccessCount")
        failureCount = UserDefaults.standard.integer(forKey: "FailureCount")
    }
    
    func toDictionary() -> [String: Any] {
        return [
            "totalInferenceTime": totalInferenceTime,
            "successCount": successCount,
            "failureCount": failureCount,
            "averageInferenceTime": averageInferenceTime,
            "successRate": successRate
        ]
    }
}

// MARK: - AI Analysis Manager
final class AIAnalysisManager: ObservableObject {
    // MARK: - Published Properties
    @Published var isAnalyzing: Bool = false
    @Published var latestResult: AnalysisResult?
    @Published var recentResults: [AnalysisResult] = []
    @Published var analysisInterval: TimeInterval = 10.0 // Default 10 seconds
    @Published var apiKey: String = "" {
        didSet {
            let keyName = usingOpenRouter ? "OpenRouterAPIKey" : "GeminiAPIKey"
            KeychainService.shared.set(value: apiKey, key: keyName)
        }
    }
    @Published var usingOpenRouter: Bool = UserDefaults.standard.bool(forKey: "UsingOpenRouter") {
        didSet {
            UserDefaults.standard.set(usingOpenRouter, forKey: "UsingOpenRouter")
        }
    }
    
    // MARK: - Statistics
    @Published var statistics = AnalysisStatistics()
    
    // MARK: - Callbacks
    var onAnalysisResult: ((AnalysisResult) -> Void)?
    var onError: ((String) -> Void)?
    
    // MARK: - Private Properties
    private var analysisTimer: Timer?
    private weak var cameraManager: CameraManager?
    private let geminiService = GeminiAPIService()
    private let openRouterService = OpenRouterAPIService()
    private let analysisQueue = DispatchQueue(label: "AIAnalysis.processing")
    private let fileManager = FileManager.default
    private let imuManager = IMUManager()
    
    // Notification and failure tracking
    private var consecutiveFailureCount: Int = 0
    private let notificationManager = NotificationManager.shared
    
    // Session and directory management
    private var sessionId: String?
    private var sessionStartTime: Date?
    
    // File paths (computed to always reflect current sessionId)
    private var documentsDirectory: URL {
        fileManager.urls(for: .documentDirectory, in: .userDomainMask)[0]
    }
    
    private var baseDirectory: URL {
        documentsDirectory.appendingPathComponent("AIAnalysis")
    }
    
    private var sessionDirectory: URL {
        guard let sessionId = sessionId else {
            fatalError("Session not initialized. Call initializeSession() first.")
        }
        return baseDirectory.appendingPathComponent("Sessions/\(sessionId)")
    }
    
    private var imagesDirectory: URL {
        sessionDirectory.appendingPathComponent("Images")
    }
    
    private var dataDirectory: URL {
        sessionDirectory.appendingPathComponent("Data")
    }
    
    private var exportDirectory: URL {
        documentsDirectory.appendingPathComponent("AIAnalysis/Export")
    }
    
    private var jsonFileURL: URL {
        dataDirectory.appendingPathComponent("analysis_results.json")
    }
    
    // Metadata file for current session
    private var metadataFileURL: URL {
        dataDirectory.appendingPathComponent("metadata.json")
    }
    
    // Prompt for analysis (default value; overridden via updateConfiguration)
    private var analysisPrompt = "Based on the image, guess what I'm doing, return only one word (English)"
    private var currentExperimentNumber: Int = {
        let exp = UserDefaults.standard.integer(forKey: "ExperimentNumber")
        return exp == 0 ? 1 : exp
    }()
    
    // MARK: - Initialization
    init() {
        // Only load settings and statistics, don't create session
        loadSettings()
        statistics.loadFromUserDefaults()
    }
    
    deinit {
        stopAnalysis()
    }
    
    // MARK: - Session Management
    
    /// Initialize new session (called when starting recording)
    func initializeSession() {
        // If session already exists, clean it first
        print("AIAnalysisManager: Cleaning existing session")
        if sessionId != nil {
            print("AIAnalysisManager: Cleaning existing session")
        }
        
        // Generate new session ID
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd_HH-mm-ss"
        self.sessionStartTime = Date()
        self.sessionId = formatter.string(from: sessionStartTime!)
        
        // Create directory structure
        setupDirectories()
        // Start IMU logging at 50 Hz into current session's Data directory
        imuManager.start(dataDirectory: dataDirectory, frequencyHz: 50.0)
        
        // Save session metadata
        saveSessionMetadata()
        
        // Reset analysis results
        recentResults.removeAll()
        latestResult = nil
        
        // Load existing results (if any)
        loadResultsFromJSON()
        
        print("AIAnalysisManager: New session initialized - \(sessionId!)")
    }
    
    /// Check if session is initialized
    var isSessionInitialized: Bool {
        return sessionId != nil
    }
    
    // MARK: - Public Methods
    func setCameraManager(_ cameraManager: CameraManager) {
        self.cameraManager = cameraManager
    }
    
    func startAnalysis() {
        guard !isAnalyzing else { return }
        guard !apiKey.isEmpty else {
            print("AIAnalysisManager: API Key not set")
            return
        }
        guard cameraManager != nil else {
            print("AIAnalysisManager: CameraManager not set")
            return
        }
        guard isSessionInitialized else {
            print("AIAnalysisManager: Session not initialized, please call initializeSession() first")
            return
        }
        
        isAnalyzing = true
        
        // Execute analysis immediately once
        performAnalysis()
        
        // Set up timer
        analysisTimer = Timer.scheduledTimer(withTimeInterval: analysisInterval, repeats: true) { [weak self] _ in
            self?.performAnalysis()
        }
        
        print("AIAnalysisManager: Starting AI analysis, interval: \(analysisInterval) seconds")
    }
    
    func stopAnalysis() {
        guard isAnalyzing else { return }
        
        analysisTimer?.invalidate()
        analysisTimer = nil
        isAnalyzing = false

        // Reset failure count when stopping analysis
        consecutiveFailureCount = 0
        print("AIAnalysisManager: Stopping AI analysis")
    }

    // Stop IMU and flush any buffered data
    func finalizeSession() {
        imuManager.stop()
    }
    
    func updateInterval(_ newInterval: TimeInterval) {
        analysisInterval = newInterval
        UserDefaults.standard.set(analysisInterval, forKey: "AnalysisInterval")
        
        // If analysis is running, restart timer
        if isAnalyzing {
            stopAnalysis()
            startAnalysis()
        }
    }
    
    func clearResults() {
        recentResults.removeAll()
        latestResult = nil
        
        // Reset failure count and clear notifications
        consecutiveFailureCount = 0
        notificationManager.clearAllNotifications()
    }
    
    func updateConfiguration(apiKey: String, prompt: String, interval: TimeInterval, usingOpenRouter: Bool) {
        self.usingOpenRouter = usingOpenRouter
        self.apiKey = apiKey
        self.analysisPrompt = prompt
        updateInterval(interval)
        // Update metadata to reflect latest prompt/config when session is active
        if isSessionInitialized {
            saveSessionMetadata()
        }
    }
    
    // MARK: - Private Methods
    private func setupDirectories() {
        do {
            try fileManager.createDirectory(at: baseDirectory, withIntermediateDirectories: true)
            try fileManager.createDirectory(at: sessionDirectory, withIntermediateDirectories: true)
            try fileManager.createDirectory(at: imagesDirectory, withIntermediateDirectories: true)
            try fileManager.createDirectory(at: dataDirectory, withIntermediateDirectories: true)
            try fileManager.createDirectory(at: exportDirectory, withIntermediateDirectories: true)
            
            print("AIAnalysisManager: Session directory created successfully - \(sessionId)")
        } catch {
            print("AIAnalysisManager: Failed to create directory - \(error)")
        }
    }
    
    private func loadSettings() {
        usingOpenRouter = UserDefaults.standard.bool(forKey: "UsingOpenRouter")
        let keyName = usingOpenRouter ? "OpenRouterAPIKey" : "GeminiAPIKey"
        apiKey = KeychainService.shared.get(key: keyName) ?? (UserDefaults.standard.string(forKey: keyName) ?? "")
        analysisInterval = UserDefaults.standard.double(forKey: "AnalysisInterval")
        if analysisInterval <= 0 {
            analysisInterval = 10.0
        }
    }
    
    private func performAnalysis() {
        analysisQueue.async { [weak self] in
            self?.captureAndAnalyze()
        }
    }
    
    private func captureAndAnalyze() {
        guard let cameraManager = cameraManager else { 
            onError?("Camera manager not initialized")
            return 
        }
        
        // Check if camera session is active
        guard cameraManager.isSessionActive() else {
            print("AIAnalysisManager: Camera session not active, skipping this analysis")
            return
        }
        
        // Record capture time
        let captureTime = Date()
        let filename = "analysis_\(Int(captureTime.timeIntervalSince1970)).jpg"
        let imagePath = imagesDirectory.appendingPathComponent(filename)
        
        // Use CameraManager's capturePhoto method
        cameraManager.capturePhoto { [weak self] imageData in
            guard let self = self, let imageData = imageData else {
                print("AIAnalysisManager: Failed to get camera frame")
                
                // Create a failure record
                let failedResult = AnalysisResult(
                    imagePath: "Camera frame acquisition failed",
                    modelOutput: "Failed to get camera frame",
                    formattedOutput: FormattedOutput(activityLabel: "camera failed"),
                    captureTime: captureTime
                )
                
                DispatchQueue.main.async { [weak self] in
                    self?.handleAnalysisResult(failedResult)
                    self?.onError?("Failed to get camera frame")
                }
                return
            }
            
            // Compress and save image
            if let compressedData = self.compressImage(imageData, quality: 0.8) {
                do {
                    try compressedData.write(to: imagePath)
                    
                    if self.usingOpenRouter {
                        self.openRouterService.analyzeImage(imageData: compressedData, prompt: self.analysisPrompt, apiKey: self.apiKey, presetSlug: "space-self-log") { result in
                            switch result {
                            case .success(let output):
                                let formattedOutput = self.formatmodelOutput(output)
                                let analysisResult = AnalysisResult(
                                    imagePath: imagePath.path,
                                    modelOutput: output,
                                    formattedOutput: formattedOutput,
                                    captureTime: captureTime
                                )
                                DispatchQueue.main.async {
                                    self.handleAnalysisResult(analysisResult)
                                }
                            case .failure(let error):
                                let errorMessage = "OpenRouter API call failed: \(error.localizedDescription)"
                                print("AIAnalysisManager: \(errorMessage)")
                                let failedResult = AnalysisResult(
                                    imagePath: imagePath.path,
                                    modelOutput: "API call failed: \(error.localizedDescription)",
                                    formattedOutput: FormattedOutput(activityLabel: "api failed"),
                                    captureTime: captureTime
                                )
                                DispatchQueue.main.async {
                                    self.handleAnalysisResult(failedResult)
                                    self.onError?(errorMessage)
                                }
                            }
                        }
                    } else {
                        self.geminiService.analyzeImage(imageData: compressedData, prompt: self.analysisPrompt, apiKey: self.apiKey) { result in
                            switch result {
                            case .success(let modelOutput):
                                let formattedOutput = self.formatmodelOutput(modelOutput)
                                let analysisResult = AnalysisResult(
                                    imagePath: imagePath.path,
                                    modelOutput: modelOutput,
                                    formattedOutput: formattedOutput,
                                    captureTime: captureTime
                                )
                                
                                DispatchQueue.main.async {
                                    self.handleAnalysisResult(analysisResult)
                                }
                                
                            case .failure(let error):
                                let errorMessage = "Gemini API call failed: \(error.localizedDescription)"
                                print("AIAnalysisManager: \(errorMessage)")
                                
                                // Create a failure record instead of skipping
                                let failedResult = AnalysisResult(
                                    imagePath: imagePath.path,
                                    modelOutput: "API call failed: \(error.localizedDescription)",
                                    formattedOutput: FormattedOutput(activityLabel: "api failed"),
                                    captureTime: captureTime
                                )
                                
                                DispatchQueue.main.async {
                                    self.handleAnalysisResult(failedResult)
                                    self.onError?(errorMessage)
                                }
                            }
                        }
                    }
                } catch {
                    let errorMessage = "Failed to save image: \(error.localizedDescription)"
                    print("AIAnalysisManager: \(errorMessage)")
                    
                    // Create a failure record
                    let failedResult = AnalysisResult(
                        imagePath: imagePath.path,
                        modelOutput: "Failed to save image: \(error.localizedDescription)",
                        formattedOutput: FormattedOutput(activityLabel: "save failed"),
                        captureTime: captureTime
                    )
                    
                    DispatchQueue.main.async {
                        self.handleAnalysisResult(failedResult)
                        self.onError?(errorMessage)
                    }
                }
            } else {
                let errorMessage = "Image compression failed"
                print("AIAnalysisManager: \(errorMessage)")
                
                // Create a failure record
                let failedResult = AnalysisResult(
                    imagePath: "Compression failed",
                    modelOutput: "Image compression failed",
                    formattedOutput: FormattedOutput(activityLabel: "compress failed"),
                    captureTime: captureTime
                )
                
                DispatchQueue.main.async {
                    self.handleAnalysisResult(failedResult)
                    self.onError?(errorMessage)
                }
            }
        }
    }
    
    private func compressImage(_ imageData: Data, quality: CGFloat) -> Data? {
        guard let image = UIImage(data: imageData) else { return nil }
        return image.jpegData(compressionQuality: quality)
    }
    
    private func handleAnalysisResult(_ result: AnalysisResult) {
        latestResult = result
        recentResults.append(result)
        
        // Limit history record count (only affects in-memory list)
        if recentResults.count > 50 {
            recentResults.removeFirst()
        }
        
        // Update statistics
        statistics.addResult(result)
        
        // Handle failure tracking and notifications
        if result.isSuccess {
            consecutiveFailureCount = 0
        } else {
            consecutiveFailureCount += 1
            notificationManager.sendAPIFailureNotification(error: result.modelOutput)
            if consecutiveFailureCount >= 3 && consecutiveFailureCount % 3 == 0 {
                notificationManager.sendContinuousFailureWarning(failureCount: consecutiveFailureCount)
            }
        }
        
        // Append to JSON file to retain full session history
        appendResultToJSON(result)
        
        onAnalysisResult?(result)
        
        print("AIAnalysisManager: Analysis completed - \(result.formattedOutput.activityLabel), inference time: \(String(format: "%.0f", result.inferenceTimeMs))ms")
    }
    
    // MARK: - JSON Data Persistence
    private func appendResultToJSON(_ newResult: AnalysisResult) {
        do {
            var allResults: [AnalysisResult] = []
            if fileManager.fileExists(atPath: jsonFileURL.path) {
                let existingData = try Data(contentsOf: jsonFileURL)
                if let decoded = try? JSONDecoder().decode([AnalysisResult].self, from: existingData) {
                    allResults = decoded
                } else if (try? JSONSerialization.jsonObject(with: existingData)) != nil {
                    // If the existing file is a valid JSON but not decodable to [AnalysisResult], recreate array with new item
                    print("AIAnalysisManager: JSON decode failed; recreating with new item appended.")
                }
            }
            allResults.append(newResult)
            let jsonData = try JSONEncoder().encode(allResults)
            try jsonData.write(to: jsonFileURL)
        } catch {
            print("AIAnalysisManager: Failed to append to JSON - \(error)")
        }
    }
    private func saveResultsToJSON() {
        do {
            let jsonData = try JSONEncoder().encode(recentResults)
            try jsonData.write(to: jsonFileURL)
        } catch {
            print("AIAnalysisManager: Failed to save JSON - \(error)")
        }
    }
    
    private func loadResultsFromJSON() {
        guard fileManager.fileExists(atPath: jsonFileURL.path) else {
            print("AIAnalysisManager: JSON file doesn't exist, using empty data")
            return
        }
        
        do {
            let jsonData = try Data(contentsOf: jsonFileURL)
            recentResults = try JSONDecoder().decode([AnalysisResult].self, from: jsonData)
            
            // Update latest result
            latestResult = recentResults.last
            
            print("AIAnalysisManager: Successfully loaded \(recentResults.count) history records")
        } catch {
            print("AIAnalysisManager: Failed to load JSON - \(error)")
            recentResults = []
        }
    }
    
    // MARK: - Data Export Functions
    func exportAnalysisData() -> URL? {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd_HH-mm-ss"
        let timestamp = formatter.string(from: Date())
        
        let exportFileName = "session_\(sessionId)_export_\(timestamp).json"
        let exportFileURL = exportDirectory.appendingPathComponent(exportFileName)
        
        do {
            let exportData: [String: Any] = [
                "sessionId": sessionId ?? "unknown",
                "sessionStartTime": ISO8601DateFormatter().string(from: sessionStartTime ?? Date()),
                "exportTime": ISO8601DateFormatter().string(from: Date()),
                "totalResults": recentResults.count,
                "prompt": analysisPrompt,
                "apiProvider": usingOpenRouter ? "OpenRouter" : "Gemini",
                "model": usingOpenRouter ? "@preset/space-self-log" : "gemini-2.5-flash",
                "intervalSeconds": analysisInterval,
                "statistics": statistics.toDictionary(),
                "results": recentResults.map { $0.toDictionary() }
            ]
            
            let jsonData = try JSONSerialization.data(withJSONObject: exportData, options: .prettyPrinted)
            try jsonData.write(to: exportFileURL)
            
            print("AIAnalysisManager: Session data export successful - \(exportFileURL.path)")
            return exportFileURL
        } catch {
            print("AIAnalysisManager: Session data export failed - \(error)")
            return nil
        }
    }
    
    func exportImagesArchive() -> URL? {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd_HH-mm-ss"
        let timestamp = formatter.string(from: Date())
        
        let archiveName = "session_\(sessionId)_images_\(timestamp).zip"
        let archiveURL = exportDirectory.appendingPathComponent(archiveName)
        
        // Here we need to implement ZIP compression functionality
        // Since iOS doesn't natively support ZIP creation, we'll create a simple folder export first
        let imagesFolderURL = exportDirectory.appendingPathComponent("session_\(sessionId)_images_\(timestamp)")
        
        do {
            try fileManager.createDirectory(at: imagesFolderURL, withIntermediateDirectories: true)
            
            // Copy all image files from current session
            let imageFiles = try fileManager.contentsOfDirectory(at: imagesDirectory, includingPropertiesForKeys: nil)
            
            for imageFile in imageFiles {
                let destinationURL = imagesFolderURL.appendingPathComponent(imageFile.lastPathComponent)
                try fileManager.copyItem(at: imageFile, to: destinationURL)
            }
            
            print("AIAnalysisManager: Session images export successful - \(imagesFolderURL.path)")
            return imagesFolderURL
        } catch {
            print("AIAnalysisManager: Session images export failed - \(error)")
            return nil
        }
    }

    // MARK: - Session Metadata
    private func saveSessionMetadata() {
        // Read experiment number from persisted settings (default to 1 if not set)
        let exp = UserDefaults.standard.integer(forKey: "ExperimentNumber")
        let experimentNumber = exp == 0 ? 1 : exp

        let metadata: [String: Any] = [
            "sessionId": sessionId ?? "unknown",
            "experimentStartTime": ISO8601DateFormatter().string(from: sessionStartTime ?? Date()),
            "prompt": analysisPrompt,
            "apiProvider": usingOpenRouter ? "OpenRouter" : "Gemini",
            "model": usingOpenRouter ? "@preset/space-self-log" : "gemini-2.5-flash",
            "intervalSeconds": analysisInterval,
            "experimentNumber": experimentNumber
        ]
        do {
            let data = try JSONSerialization.data(withJSONObject: metadata, options: .prettyPrinted)
            try data.write(to: metadataFileURL)
            print("AIAnalysisManager: Session metadata saved - \(metadataFileURL.path)")
        } catch {
            print("AIAnalysisManager: Failed to save session metadata - \(error)")
        }
    }

    /// Update experiment number and persist; refresh metadata for current session
    func updateExperiment(_ number: Int) {
        let minId = ExperimentRegistry.minId
        let maxId = ExperimentRegistry.maxId
        let clamped = max(minId, min(maxId, number))
        UserDefaults.standard.set(clamped, forKey: "ExperimentNumber")
        currentExperimentNumber = clamped
        if isSessionInitialized {
            saveSessionMetadata()
        }
    }
    
    func clearAllData() {
        // Clear data in memory
        recentResults.removeAll()
        latestResult = nil
        statistics.reset()
        
        // Delete JSON file
        if fileManager.fileExists(atPath: jsonFileURL.path) {
            try? fileManager.removeItem(at: jsonFileURL)
        }
        
        // Delete all image files
        do {
            let imageFiles = try fileManager.contentsOfDirectory(at: imagesDirectory, includingPropertiesForKeys: nil)
            for imageFile in imageFiles {
                try fileManager.removeItem(at: imageFile)
            }
        } catch {
            print("AIAnalysisManager: Failed to clear image files - \(error)")
        }
        
        print("AIAnalysisManager: All data cleared")
    }
    
    func getStorageInfo() -> [String: Any] {
        // If session not initialized, return default values
        guard isSessionInitialized else {
            return [
                "sessionId": "Not initialized",
                "sessionStartTime": Date(),
                "imageCount": 0,
                "totalImageSize": 0,
                "jsonSize": 0,
                "totalSize": 0,
                "resultsCount": 0
            ]
        }
        
        var totalImageSize: Int64 = 0
        var imageCount = 0
        
        do {
            let imageFiles = try fileManager.contentsOfDirectory(at: imagesDirectory, includingPropertiesForKeys: [.fileSizeKey])
            imageCount = imageFiles.count
            
            for imageFile in imageFiles {
                let attributes = try fileManager.attributesOfItem(atPath: imageFile.path)
                if let fileSize = attributes[.size] as? Int64 {
                    totalImageSize += fileSize
                }
            }
        } catch {
            print("AIAnalysisManager: Failed to get storage info - \(error)")
        }
        
        var jsonSize: Int64 = 0
        var resultsCount: Int = 0
        if fileManager.fileExists(atPath: jsonFileURL.path) {
            do {
                let attributes = try fileManager.attributesOfItem(atPath: jsonFileURL.path)
                jsonSize = attributes[.size] as? Int64 ?? 0
            } catch {
                print("AIAnalysisManager: Failed to get JSON file size - \(error)")
            }
            
            // Read JSON array length as the true results count
            do {
                let jsonData = try Data(contentsOf: jsonFileURL)
                if let jsonArray = try JSONSerialization.jsonObject(with: jsonData) as? [Any] {
                    resultsCount = jsonArray.count
                } else {
                    // Fallback to decoding typed array
                    resultsCount = (try? JSONDecoder().decode([AnalysisResult].self, from: jsonData).count) ?? 0
                }
            } catch {
                print("AIAnalysisManager: Failed to get JSON record count - \(error)")
            }
        }
        
        return [
            "sessionId": sessionId ?? "Unknown",
            "sessionStartTime": sessionStartTime ?? Date(),
            "imageCount": imageCount,
            "totalImageSize": totalImageSize,
            "jsonSize": jsonSize,
            "totalSize": totalImageSize + jsonSize,
            "resultsCount": resultsCount
        ]
    }
    
    private func formatmodelOutput(_ output: String) -> FormattedOutput {
        let mode = ExperimentRegistry.mode(for: currentExperimentNumber)
        // Be flexible: try formatting first to salvage activityLabel even if some keys are imperfect
        return mode.format(output)
    }
    
    // MARK: - Historical Sessions Management
    
    /// Get all historical sessions information
    func getHistoricalSessions() -> [SessionInfo] {
        let sessionsDirectory = baseDirectory.appendingPathComponent("Sessions")
        
        guard fileManager.fileExists(atPath: sessionsDirectory.path) else {
            return []
        }
        
        do {
            let sessionFolders = try fileManager.contentsOfDirectory(atPath: sessionsDirectory.path)
            var sessions: [SessionInfo] = []
            
            for folderName in sessionFolders {
                let sessionPath = sessionsDirectory.appendingPathComponent(folderName)
                
                // Check if it's a directory
                var isDirectory: ObjCBool = false
                guard fileManager.fileExists(atPath: sessionPath.path, isDirectory: &isDirectory),
                      isDirectory.boolValue else {
                    continue
                }
                
                // Try to parse time from folder name
                if let sessionTime = parseSessionTime(from: folderName) {
                    let sessionInfo = getSessionInfo(sessionId: folderName, sessionTime: sessionTime, sessionPath: sessionPath)
                    sessions.append(sessionInfo)
                }
            }
            
            // Sort by time in descending order (newest first)
            return sessions.sorted { $0.startTime > $1.startTime }
            
        } catch {
            print("Failed to get historical sessions: \(error)")
            return []
        }
    }
    
    /// Parse session time
    private func parseSessionTime(from sessionId: String) -> Date? {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd_HH-mm-ss"
        return formatter.date(from: sessionId)
    }
    
    /// Get detailed information for a single session
    private func getSessionInfo(sessionId: String, sessionTime: Date, sessionPath: URL) -> SessionInfo {
        let dataPath = sessionPath.appendingPathComponent("Data")
        let imagesPath = sessionPath.appendingPathComponent("Images")
        let jsonPath = dataPath.appendingPathComponent("analysis_results.json")
        
        var recordCount = 0
        var imageCount = 0
        var totalSize: Int64 = 0
        
        // Read JSON file to get record count
        if fileManager.fileExists(atPath: jsonPath.path) {
            do {
                let jsonData = try Data(contentsOf: jsonPath)
                if let jsonArray = try JSONSerialization.jsonObject(with: jsonData) as? [[String: Any]] {
                    recordCount = jsonArray.count
                }
                
                let attributes = try fileManager.attributesOfItem(atPath: jsonPath.path)
                if let fileSize = attributes[.size] as? Int64 {
                    totalSize += fileSize
                }
            } catch {
                print("Failed to read session JSON file: \(error)")
            }
        }
        
        // Count images and calculate size
        if fileManager.fileExists(atPath: imagesPath.path) {
            do {
                let imageFiles = try fileManager.contentsOfDirectory(atPath: imagesPath.path)
                imageCount = imageFiles.count
                
                for imageFile in imageFiles {
                    let imagePath = imagesPath.appendingPathComponent(imageFile)
                    do {
                        let attributes = try fileManager.attributesOfItem(atPath: imagePath.path)
                        if let fileSize = attributes[.size] as? Int64 {
                            totalSize += fileSize
                        }
                    } catch {
                        print("Failed to get image file size: \(error)")
                    }
                }
            } catch {
                print("Failed to read images directory: \(error)")
            }
        }
        
        return SessionInfo(
            sessionId: sessionId,
            startTime: sessionTime,
            recordCount: recordCount,
            imageCount: imageCount,
            totalSize: totalSize,
            isCurrentSession: sessionId == self.sessionId
        )
    }
    
    /// Delete specified historical session
    func deleteHistoricalSession(sessionId: String) -> Bool {
        // Don't allow deleting current session
        guard sessionId != self.sessionId else {
            print("Cannot delete currently active session")
            return false
        }
        
        let sessionPath = baseDirectory.appendingPathComponent("Sessions/\(sessionId)")
        
        do {
            try fileManager.removeItem(at: sessionPath)
            return true
        } catch {
            print("Failed to delete session: \(error)")
            return false
        }
    }
}

// MARK: - SessionInfo Structure

struct SessionInfo {
    let sessionId: String
    let startTime: Date
    let recordCount: Int
    let imageCount: Int
    let totalSize: Int64
    let isCurrentSession: Bool
    
    var formattedStartTime: String {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd HH:mm:ss"
        return formatter.string(from: startTime)
    }
    
    var formattedSize: String {
        let formatter = ByteCountFormatter()
        formatter.allowedUnits = [.useKB, .useMB, .useGB]
        formatter.countStyle = .file
        return formatter.string(fromByteCount: totalSize)
    }
}
