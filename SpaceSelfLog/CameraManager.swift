import Foundation
import AVFoundation
import CoreImage
import ImageIO
import UniformTypeIdentifiers

enum CameraError: Error, LocalizedError {
    case deviceNotFound(String)
    case cannotAddInput
    case cannotAddOutput
    case sessionNotConfigured
    case permissionDenied
    
    var errorDescription: String? {
        switch self {
        case .deviceNotFound(let cameraType):
            return "Camera device not found: \(cameraType)"
        case .cannotAddInput:
            return "Cannot add camera input"
        case .cannotAddOutput:
            return "Cannot add video output"
        case .sessionNotConfigured:
            return "Camera session not properly configured"
        case .permissionDenied:
            return "Camera permission denied"
        }
    }
}

enum CameraType: String, CaseIterable {
    case wide = "wide"
    case ultra = "ultra"
}

enum RotationAngle: Int, CaseIterable {
    case degrees0 = 0
    case degrees90 = 90
    case degrees180 = 180
    case degrees270 = 270
    
    var next: RotationAngle {
        switch self {
        case .degrees0: return .degrees90
        case .degrees90: return .degrees180
        case .degrees180: return .degrees270
        case .degrees270: return .degrees0
        }
    }
    
    var radians: Double {
        return Double(self.rawValue) * .pi / 180.0
    }
}

enum ResolutionPreset: String, CaseIterable {
    case low = "low"           // 480p
    case medium = "medium"     // 720p
    case high = "high"         // 1080p
    case ultra = "ultra"       // 4K
    
    var sessionPreset: AVCaptureSession.Preset {
        switch self {
        case .low: return .vga640x480
        case .medium: return .hd1280x720
        case .high: return .hd1920x1080
        case .ultra: return .hd4K3840x2160
        }
    }
    
    var displayName: String {
        switch self {
        case .low: return "480p"
        case .medium: return "720p"
        case .high: return "1080p"
        case .ultra: return "4K"
        }
    }
}

final class CameraManager: NSObject {
    private let session = AVCaptureSession()
    private var videoOutput = AVCaptureVideoDataOutput()
    private var currentInput: AVCaptureDeviceInput?
    private let ciContext = CIContext()
    private let outputQueue = DispatchQueue(label: "CameraManager.videoOutput")
    private let sessionQueue = DispatchQueue(label: "CameraManager.session")
    
    // Error handling
    private var isSessionConfigured = false
    private var lastKnownWorkingCamera: CameraType?
    
    // Session lifecycle management
    private var sessionObservers: [NSObjectProtocol] = []
    private var isSessionRunning = false
    
    // Rotation state
    private var currentRotation: RotationAngle = .degrees0
    private let rotationKey = "CameraRotationAngle"
    
    // Camera selection state
    private var selectedCamera: CameraType = .wide
    private let cameraSelectionKey = "SelectedCameraType"
    
    // Resolution state
    private var selectedResolution: ResolutionPreset = .high
    private let resolutionKey = "SelectedResolution"

    var onFrame: ((Data) -> Void)?
    var onError: ((String) -> Void)?
    var onSessionStateChanged: ((Bool) -> Void)?
    var onRotationChanged: ((RotationAngle) -> Void)?
    var onCameraChanged: ((CameraType) -> Void)?
    var onResolutionChanged: ((ResolutionPreset) -> Void)?
    
    // AI Analysis support
    private var capturePhotoCompletion: ((Data?) -> Void)?
    
    override init() {
        super.init()
        loadRotationState()
        loadCameraSelection()
        loadResolutionState()
        setupSessionObservers()
    }
    
    deinit {
        removeSessionObservers()
        cleanupSession()
    }
    
    // MARK: - Session Lifecycle Management
    private func setupSessionObservers() {
        let notificationCenter = NotificationCenter.default
        
        // Session runtime error
        let runtimeErrorObserver = notificationCenter.addObserver(
            forName: .AVCaptureSessionRuntimeError,
            object: session,
            queue: .main
        ) { [weak self] notification in
            guard let error = notification.userInfo?[AVCaptureSessionErrorKey] as? AVError else { return }
            self?.handleSessionRuntimeError(error)
        }
        sessionObservers.append(runtimeErrorObserver)
        
        // Session started running
        let startObserver = notificationCenter.addObserver(
            forName: .AVCaptureSessionDidStartRunning,
            object: session,
            queue: .main
        ) { [weak self] _ in
            self?.isSessionRunning = true
            self?.onSessionStateChanged?(true)
            print("CameraManager: Session started running")
        }
        sessionObservers.append(startObserver)
        
        // Session stopped running
        let stopObserver = notificationCenter.addObserver(
            forName: .AVCaptureSessionDidStopRunning,
            object: session,
            queue: .main
        ) { [weak self] _ in
            self?.isSessionRunning = false
            self?.onSessionStateChanged?(false)
            print("CameraManager: Session stopped running")
        }
        sessionObservers.append(stopObserver)
        
        // Session was interrupted
        let interruptionObserver = notificationCenter.addObserver(
            forName: .AVCaptureSessionWasInterrupted,
            object: session,
            queue: .main
        ) { [weak self] notification in
            if let reason = notification.userInfo?[AVCaptureSessionInterruptionReasonKey] as? AVCaptureSession.InterruptionReason {
                self?.handleSessionInterruption(reason)
            }
        }
        sessionObservers.append(interruptionObserver)
        
        // Session interruption ended
        let interruptionEndObserver = notificationCenter.addObserver(
            forName: .AVCaptureSessionInterruptionEnded,
            object: session,
            queue: .main
        ) { [weak self] _ in
            self?.handleSessionInterruptionEnded()
        }
        sessionObservers.append(interruptionEndObserver)
    }
    
    private func removeSessionObservers() {
        let notificationCenter = NotificationCenter.default
        sessionObservers.forEach { notificationCenter.removeObserver($0) }
        sessionObservers.removeAll()
    }
    
    private func cleanupSession() {
        sessionQueue.sync {
            if session.isRunning {
                session.stopRunning()
            }
            
            session.beginConfiguration()
            
            for input in session.inputs {
                session.removeInput(input)
            }
            
            for output in session.outputs {
                session.removeOutput(output)
            }
            
            session.commitConfiguration()
            
            currentInput = nil
            isSessionConfigured = false
            isSessionRunning = false
        }
    }
    
    private func handleSessionRuntimeError(_ error: AVError) {
        print("CameraManager Error: Session runtime error: \(error.localizedDescription)")
        
        // Try to restart session for recoverable errors
        if error.code == .mediaServicesWereReset {
            sessionQueue.async { [weak self] in
                if let lastCamera = self?.lastKnownWorkingCamera {
                    print("CameraManager: Attempting to restart session")
                    do {
                        try self?.configureSession(camera: lastCamera)
                        self?.session.startRunning()
                    } catch {
                        print("CameraManager Error: Session restart failed: \(error.localizedDescription)")
                        DispatchQueue.main.async {
                            self?.onError?("Session restart failed: \(error.localizedDescription)")
                        }
                    }
                }
            }
        } else {
            onError?("Camera runtime error: \(error.localizedDescription)")
        }
    }
    
    private func handleSessionInterruption(_ reason: AVCaptureSession.InterruptionReason) {
        print("CameraManager: Session interrupted, reason: \(reason)")
        
        switch reason {
        case .audioDeviceInUseByAnotherClient:
            print("CameraManager: Audio device occupied by other app")
        case .videoDeviceInUseByAnotherClient:
            print("CameraManager: Camera occupied by other app")
            onError?("Camera occupied by other app")
        case .videoDeviceNotAvailableWithMultipleForegroundApps:
            print("CameraManager: Multiple foreground apps causing camera unavailable")
            onError?("Multiple apps using camera simultaneously")
        case .videoDeviceNotAvailableDueToSystemPressure:
            print("CameraManager: System pressure causing camera unavailable")
            onError?("Insufficient system resources, camera temporarily unavailable")
        @unknown default:
            print("CameraManager: Unknown interruption reason")
        }
    }
    
    private func handleSessionInterruptionEnded() {
        print("CameraManager: Session interruption ended")
        
        // Try to restart session if it was configured
        if isSessionConfigured, let lastCamera = lastKnownWorkingCamera {
            sessionQueue.async { [weak self] in
                if !(self?.session.isRunning ?? false) {
                    print("CameraManager: Restarting session")
                    self?.session.startRunning()
                }
            }
        }
    }

    // Discover available back cameras
    func discoverCameras() -> [CameraType] {
        var set: Set<CameraType> = []
        let discovery = AVCaptureDevice.DiscoverySession(
            deviceTypes: [.builtInWideAngleCamera, .builtInUltraWideCamera],
            mediaType: .video,
            position: .back
        )
        
        for device in discovery.devices {
            // Validate device availability
            guard !device.isSuspended, 
                  device.isConnected,
                  !device.hasMediaType(.video) || device.supportsSessionPreset(.high) else {
                continue
            }
            
            switch device.deviceType {
            case .builtInUltraWideCamera: set.insert(.ultra)
            case .builtInWideAngleCamera: set.insert(.wide)
            default: break
            }
        }
        // Keep order wide -> ultra for UX
        return CameraType.allCases.filter { set.contains($0) }
    }

    func start(camera: CameraType) {
        // Validate camera availability first
        let availableCameras = discoverCameras()
        guard availableCameras.contains(camera) else {
            let errorMsg = "Requested camera type \(camera.rawValue) unavailable"
            print("CameraManager Error: \(errorMsg)")
            onError?(errorMsg)
            
            // Try fallback to any available camera
            if let fallbackCamera = availableCameras.first {
                print("CameraManager: Attempting to use fallback camera \(fallbackCamera.rawValue)")
                start(camera: fallbackCamera)
            }
            return
        }
        
        // Perform detailed device validation
        guard validateCameraDevice(camera) else {
            let errorMsg = "Camera device \(camera.rawValue) health check failed"
            print("CameraManager Error: \(errorMsg)")
            onError?(errorMsg)
            
            // Try fallback to other available cameras
            for fallbackCamera in availableCameras where fallbackCamera != camera {
                if validateCameraDevice(fallbackCamera) {
                    print("CameraManager: Attempting to use healthy fallback camera \(fallbackCamera.rawValue)")
                    start(camera: fallbackCamera)
                    return
                }
            }
            return
        }
        
        // Check camera permission first
        checkCameraPermission { [weak self] granted in
            guard granted else {
                let errorMsg = "Camera permission denied"
                print("CameraManager Error: \(errorMsg)")
                self?.onError?(errorMsg)
                return
            }
            
            // Perform session operations on background thread
            self?.sessionQueue.async {
                do {
                    try self?.configureSession(camera: camera)
                    self?.session.startRunning()
                    self?.selectedCamera = camera
                    self?.saveCameraSelection()
                    self?.lastKnownWorkingCamera = camera
                    self?.isSessionConfigured = true
                    DispatchQueue.main.async {
                        self?.onCameraChanged?(camera)
                    }
                    print("CameraManager: Successfully started camera \(camera.rawValue)")
                } catch {
                    let errorMsg = "Camera configuration failed: \(error.localizedDescription)"
                    print("CameraManager Error: \(errorMsg)")
                    DispatchQueue.main.async {
                        self?.onError?(errorMsg)
                    }
                }
            }
        }
    }

    func stop() {
        sessionQueue.async { [weak self] in
            guard let self = self, self.isSessionConfigured else { return }
            
            if self.session.isRunning {
                self.session.stopRunning()
            }
            
            // Clean up session
            self.session.beginConfiguration()
            
            // Remove all inputs and outputs
            for input in self.session.inputs {
                self.session.removeInput(input)
            }
            
            for output in self.session.outputs {
                self.session.removeOutput(output)
            }
            
            self.session.commitConfiguration()
            
            self.currentInput = nil
            self.isSessionConfigured = false
            
            print("CameraManager: 摄像头已停止")
        }
    }

    func switchCamera(to camera: CameraType) {
        // Validate camera availability first
        let availableCameras = discoverCameras()
        guard availableCameras.contains(camera) else {
            let errorMsg = "无法切换到摄像头 \(camera.rawValue)：设备不可用"
            print("CameraManager Error: \(errorMsg)")
            onError?(errorMsg)
            return
        }
        
        sessionQueue.async { [weak self] in
            guard let self = self, self.isSessionConfigured else {
                let errorMsg = "摄像头会话未配置，无法切换摄像头"
                print("CameraManager Error: \(errorMsg)")
                DispatchQueue.main.async {
                    self?.onError?(errorMsg)
                }
                return
            }
            
            do {
                try self.configureSession(camera: camera)
                self.selectedCamera = camera
                self.saveCameraSelection()
                self.lastKnownWorkingCamera = camera
                DispatchQueue.main.async {
                    self.onCameraChanged?(camera)
                }
                print("CameraManager: 成功切换到摄像头 \(camera.rawValue)")
            } catch {
                let errorMsg = "切换摄像头失败: \(error.localizedDescription)"
                print("CameraManager Error: \(errorMsg)")
                DispatchQueue.main.async {
                    self.onError?(errorMsg)
                }
                
                // Try to recover with last known working camera
                if let lastWorking = self.lastKnownWorkingCamera, lastWorking != camera {
                    print("CameraManager: 尝试恢复到上次工作的摄像头 \(lastWorking.rawValue)")
                    do {
                        try self.configureSession(camera: lastWorking)
                    } catch {
                        print("CameraManager Error: 恢复摄像头失败: \(error.localizedDescription)")
                    }
                }
            }
        }
    }

    private func configureSession(camera: CameraType) throws {
        session.beginConfiguration()
        
        // Remove existing inputs
        for input in session.inputs {
            session.removeInput(input)
        }
        
        // Remove existing outputs
        for output in session.outputs {
            session.removeOutput(output)
        }
        
        // Add new input
        guard let input = buildInput(for: camera) else {
            session.commitConfiguration()
            throw CameraError.deviceNotFound(camera.rawValue)
        }
        
        guard session.canAddInput(input) else {
            session.commitConfiguration()
            throw CameraError.cannotAddInput
        }
        
        session.addInput(input)
        currentInput = input
        
        // Configure video output
        videoOutput.setSampleBufferDelegate(self, queue: outputQueue)
        videoOutput.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
        // Drop late frames to avoid queue buildup and reduce latency
        videoOutput.alwaysDiscardsLateVideoFrames = true
        
        guard session.canAddOutput(videoOutput) else {
            session.commitConfiguration()
            throw CameraError.cannotAddOutput
        }
        
        session.addOutput(videoOutput)
        
        // Set session preset based on selected resolution
        let desiredPreset = selectedResolution.sessionPreset
        if session.canSetSessionPreset(desiredPreset) {
            session.sessionPreset = desiredPreset
        } else if session.canSetSessionPreset(.high) {
            session.sessionPreset = .high
        }
        
        session.commitConfiguration()
    }

    private func buildInput(for camera: CameraType) -> AVCaptureDeviceInput? {
        let deviceType: AVCaptureDevice.DeviceType = (camera == .ultra) ? .builtInUltraWideCamera : .builtInWideAngleCamera
        let discovery = AVCaptureDevice.DiscoverySession(
            deviceTypes: [deviceType],
            mediaType: .video,
            position: .back
        )
        
        // Find and validate the device
        guard let device = discovery.devices.first else {
            print("CameraManager Error: 找不到 \(camera.rawValue) 摄像头设备")
            return nil
        }
        
        // Validate device availability and capabilities
        guard !device.isSuspended,
              device.isConnected,
              device.hasMediaType(.video) else {
            print("CameraManager Error: \(camera.rawValue) 摄像头设备不可用或不支持视频")
            return nil
        }
        
        // Check if device supports required formats
        guard device.supportsSessionPreset(.high) || 
              device.supportsSessionPreset(.medium) else {
            print("CameraManager Error: \(camera.rawValue) 摄像头不支持所需的视频质量")
            return nil
        }
        
        // Create input
        do {
            let input = try AVCaptureDeviceInput(device: device)
            print("CameraManager: 成功创建 \(camera.rawValue) 摄像头输入")
            return input
        } catch {
            print("CameraManager Error: 创建 \(camera.rawValue) 摄像头输入失败: \(error.localizedDescription)")
            return nil
        }
    }
    
    // MARK: - Device Validation
    private func validateCameraDevice(_ camera: CameraType) -> Bool {
        let deviceType: AVCaptureDevice.DeviceType = (camera == .ultra) ? .builtInUltraWideCamera : .builtInWideAngleCamera
        let discovery = AVCaptureDevice.DiscoverySession(
            deviceTypes: [deviceType],
            mediaType: .video,
            position: .back
        )
        
        guard let device = discovery.devices.first else {
            print("CameraManager: \(camera.rawValue) 摄像头设备不存在")
            return false
        }
        
        // Check device health
        let isHealthy = !device.isSuspended && 
                       device.isConnected && 
                       device.hasMediaType(.video) &&
                       (device.supportsSessionPreset(.high) || device.supportsSessionPreset(.medium))
        
        if !isHealthy {
            print("CameraManager: \(camera.rawValue) 摄像头设备健康检查失败")
            print("  - 暂停状态: \(device.isSuspended)")
            print("  - 连接状态: \(device.isConnected)")
            print("  - 视频支持: \(device.hasMediaType(.video))")
            print("  - 质量支持: \(device.supportsSessionPreset(.high) || device.supportsSessionPreset(.medium))")
        }
        
        return isHealthy
    }
    
    // MARK: - Permission Check
    private func checkCameraPermission(completion: @escaping (Bool) -> Void) {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            completion(true)
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { granted in
                DispatchQueue.main.async {
                    completion(granted)
                }
            }
        case .denied, .restricted:
            completion(false)
        @unknown default:
            completion(false)
        }
    }
    
    // MARK: - Photo Capture for AI Analysis
    func capturePhoto(completion: @escaping (Data?) -> Void) {
        guard isSessionRunning else {
            completion(nil)
            return
        }
        
        // Set the completion handler to capture the next frame
        capturePhotoCompletion = completion
        
        // If no frame comes within 2 seconds, timeout
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.0) { [weak self] in
            if self?.capturePhotoCompletion != nil {
                self?.capturePhotoCompletion = nil
                completion(nil)
            }
        }
    }
}

// MARK: - Delegate
extension CameraManager: AVCaptureVideoDataOutputSampleBufferDelegate {
    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {
        guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        let ciImage = CIImage(cvPixelBuffer: pixelBuffer)
        
        // Apply rotation if needed
        let rotatedImage = applyRotation(to: ciImage)
        
        guard let cgImage = ciContext.createCGImage(rotatedImage, from: rotatedImage.extent) else { return }

        // Encode JPEG for MJPEG streaming
        let data = NSMutableData()
        // Use UniformTypeIdentifiers (UTType.jpeg)
        guard let dest = CGImageDestinationCreateWithData(data, UTType.jpeg.identifier as CFString, 1, nil) else { return }
        CGImageDestinationAddImage(dest, cgImage, [kCGImageDestinationLossyCompressionQuality as String: 0.6] as CFDictionary)
        guard CGImageDestinationFinalize(dest) else { return }

        let frameData = data as Data
        
        // Handle photo capture if requested
        if let completion = capturePhotoCompletion {
            capturePhotoCompletion = nil
            completion(frameData)
        }
        
        // Send frame for streaming
        onFrame?(frameData)
    }
}

// MARK: - Rotation Management
extension CameraManager {
    private func loadRotationState() {
        let savedRotation = UserDefaults.standard.integer(forKey: rotationKey)
        if let rotation = RotationAngle(rawValue: savedRotation) {
            currentRotation = rotation
        }
    }
    
    private func saveRotationState() {
        UserDefaults.standard.set(currentRotation.rawValue, forKey: rotationKey)
    }
    
    func rotateCamera() {
        currentRotation = currentRotation.next
        saveRotationState()
        onRotationChanged?(currentRotation)
        print("CameraManager: Rotated to \(currentRotation.rawValue)°")
    }
    
    func getCurrentRotation() -> RotationAngle {
        return currentRotation
    }
    
    private func applyRotation(to ciImage: CIImage) -> CIImage {
        guard currentRotation != .degrees0 else { return ciImage }
        
        let transform = CGAffineTransform(rotationAngle: CGFloat(currentRotation.radians))
        return ciImage.transformed(by: transform)
    }
}

// MARK: - Camera Selection Management
extension CameraManager {
    private func loadCameraSelection() {
        let savedCamera = UserDefaults.standard.string(forKey: cameraSelectionKey)
        if let cameraString = savedCamera, let camera = CameraType(rawValue: cameraString) {
            selectedCamera = camera
        }
    }
    
    private func saveCameraSelection() {
        UserDefaults.standard.set(selectedCamera.rawValue, forKey: cameraSelectionKey)
    }
    
    func getSelectedCamera() -> CameraType {
        return selectedCamera
    }
}

// MARK: - Resolution Management
extension CameraManager {
    private func loadResolutionState() {
        if let savedResolutionString = UserDefaults.standard.string(forKey: resolutionKey),
           let savedResolution = ResolutionPreset(rawValue: savedResolutionString) {
            selectedResolution = savedResolution
        }
    }
    
    private func saveResolutionState() {
        UserDefaults.standard.set(selectedResolution.rawValue, forKey: resolutionKey)
    }
    
    func switchResolution(to resolution: ResolutionPreset) {
        guard resolution != selectedResolution else { return }
        
        sessionQueue.async { [weak self] in
            guard let self = self else { return }
            
            self.selectedResolution = resolution
            self.saveResolutionState()
            
            // If session is running, reconfigure it with new resolution
            if self.isSessionRunning {
                do {
                    try self.configureSession(camera: self.selectedCamera)
                    print("CameraManager: Successfully switched resolution to \(resolution.displayName)")
                    
                    DispatchQueue.main.async {
                        self.onResolutionChanged?(resolution)
                    }
                } catch {
                    print("CameraManager: Resolution switch failed: \(error.localizedDescription)")
                    DispatchQueue.main.async {
                        self.onError?("Resolution switch failed: \(error.localizedDescription)")
                    }
                }
            } else {
                DispatchQueue.main.async {
                    self.onResolutionChanged?(resolution)
                }
            }
        }
    }
    
    func getSelectedResolution() -> ResolutionPreset {
        return selectedResolution
    }
    
    func getAvailableResolutions() -> [ResolutionPreset] {
        return ResolutionPreset.allCases
    }
    
    // MARK: - Session Status
    func isSessionActive() -> Bool {
        return isSessionRunning && session.isRunning
    }
}