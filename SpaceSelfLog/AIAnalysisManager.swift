import Foundation

// MARK: - Session Manager
// Manages the on-disk session directory for each recording.
// Sessions/<date>/
//   Data/  metadata.json  imu_accelerometer.csv
//   frames/  frame_NNNN.jpg  frame_NNNN.json

final class AIAnalysisManager {

    // MARK: - Session State
    private(set) var sessionId: String?
    private(set) var sessionStartTime: Date?

    private let fileManager = FileManager.default

    var isSessionInitialized: Bool { sessionId != nil }

    // MARK: - Directory Layout

    private var documentsDirectory: URL {
        fileManager.urls(for: .documentDirectory, in: .userDomainMask)[0]
    }

    private var baseDirectory: URL {
        documentsDirectory.appendingPathComponent("Sessions")
    }

    var sessionDirectory: URL {
        guard let id = sessionId else {
            fatalError("Call initializeSession() first.")
        }
        return baseDirectory.appendingPathComponent(id)
    }

    var dataDirectory: URL {
        sessionDirectory.appendingPathComponent("Data")
    }

    private var metadataFileURL: URL {
        dataDirectory.appendingPathComponent("metadata.json")
    }

    // MARK: - Lifecycle

    func initializeSession() {
        let fmt = DateFormatter()
        fmt.dateFormat = "yyyy-MM-dd_HH-mm-ss"
        sessionStartTime = Date()
        sessionId = fmt.string(from: sessionStartTime!)
        setupDirectories()
        saveSessionMetadata()
        print("SessionManager: new session — \(sessionId!)")
    }

    func finalizeSession() { }

    // MARK: - Private

    private func setupDirectories() {
        do {
            try fileManager.createDirectory(at: baseDirectory, withIntermediateDirectories: true)
            try fileManager.createDirectory(at: sessionDirectory, withIntermediateDirectories: true)
            try fileManager.createDirectory(at: dataDirectory, withIntermediateDirectories: true)
        } catch {
            print("SessionManager: failed to create dirs — \(error)")
        }
    }

    private func saveSessionMetadata() {
        let ud = UserDefaults.standard
        let meta: [String: Any] = [
            "sessionId": sessionId ?? "unknown",
            "startTime": ISO8601DateFormatter().string(from: sessionStartTime ?? Date()),
            "captureMinInterval": ud.integer(forKey: "CaptureMinInterval"),
            "captureMaxInterval": ud.integer(forKey: "CaptureMaxInterval"),
            "sustainedMotionThreshold": ud.integer(forKey: "SustainedMotionThreshold")
        ]
        if let data = try? JSONSerialization.data(withJSONObject: meta, options: .prettyPrinted) {
            try? data.write(to: metadataFileURL)
        }
    }

    // MARK: - Storage Info

    func getStorageInfo() -> [String: Any] {
        guard isSessionInitialized else {
            return [
                "sessionId": "Not initialized",
                "sessionStartTime": Date(),
                "frameCount": 0,
                "totalFrameSize": Int64(0),
                "totalDataSize": Int64(0)
            ]
        }
        let framesDir = sessionDirectory.appendingPathComponent("frames")
        var frameCount = 0
        var totalFrameSize: Int64 = 0
        if let files = try? fileManager.contentsOfDirectory(at: framesDir, includingPropertiesForKeys: [.fileSizeKey]) {
            let jpegs = files.filter { $0.pathExtension == "jpg" }
            frameCount = jpegs.count
            for f in jpegs {
                if let attrs = try? fileManager.attributesOfItem(atPath: f.path),
                   let sz = attrs[.size] as? Int64 { totalFrameSize += sz }
            }
        }
        var imuSize: Int64 = 0
        let imuURL = dataDirectory.appendingPathComponent("imu_accelerometer.csv")
        if let attrs = try? fileManager.attributesOfItem(atPath: imuURL.path),
           let sz = attrs[.size] as? Int64 { imuSize = sz }

        return [
            "sessionId": sessionId ?? "Unknown",
            "sessionStartTime": sessionStartTime ?? Date(),
            "frameCount": frameCount,
            "totalFrameSize": totalFrameSize,
            "totalDataSize": totalFrameSize + imuSize
        ]
    }

    func clearAllData() {
        guard isSessionInitialized else { return }
        let framesDir = sessionDirectory.appendingPathComponent("frames")
        if let files = try? fileManager.contentsOfDirectory(at: framesDir, includingPropertiesForKeys: nil) {
            for f in files { try? fileManager.removeItem(at: f) }
        }
        print("SessionManager: frames cleared")
    }

    // MARK: - Historical Sessions

    func getHistoricalSessions() -> [SessionInfo] {
        guard fileManager.fileExists(atPath: baseDirectory.path) else { return [] }
        let folders = (try? fileManager.contentsOfDirectory(atPath: baseDirectory.path)) ?? []
        let fmt = DateFormatter()
        fmt.dateFormat = "yyyy-MM-dd_HH-mm-ss"
        return folders.compactMap { name -> SessionInfo? in
            guard let date = fmt.date(from: name) else { return nil }
            let path = baseDirectory.appendingPathComponent(name)
            var isDir: ObjCBool = false
            guard fileManager.fileExists(atPath: path.path, isDirectory: &isDir), isDir.boolValue else { return nil }
            return buildSessionInfo(id: name, date: date, path: path)
        }.sorted { $0.startTime > $1.startTime }
    }

    func deleteHistoricalSession(sessionId: String) -> Bool {
        guard sessionId != self.sessionId else { return false }
        let path = baseDirectory.appendingPathComponent(sessionId)
        do {
            try fileManager.removeItem(at: path)
            return true
        } catch {
            print("SessionManager: delete failed — \(error)")
            return false
        }
    }

    private func buildSessionInfo(id: String, date: Date, path: URL) -> SessionInfo {
        let framesDir = path.appendingPathComponent("frames")
        var frameCount = 0
        var totalSize: Int64 = 0
        if let files = try? fileManager.contentsOfDirectory(at: framesDir, includingPropertiesForKeys: [.fileSizeKey]) {
            let jpegs = files.filter { $0.pathExtension == "jpg" }
            frameCount = jpegs.count
            for f in jpegs {
                if let attrs = try? fileManager.attributesOfItem(atPath: f.path),
                   let sz = attrs[.size] as? Int64 { totalSize += sz }
            }
        }
        return SessionInfo(sessionId: id, startTime: date, frameCount: frameCount, totalSize: totalSize, isCurrentSession: id == self.sessionId)
    }
}

// MARK: - SessionInfo

struct SessionInfo {
    let sessionId: String
    let startTime: Date
    let frameCount: Int
    let totalSize: Int64
    let isCurrentSession: Bool

    var formattedStartTime: String {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd HH:mm:ss"
        return f.string(from: startTime)
    }

    var formattedSize: String {
        let f = ByteCountFormatter()
        f.allowedUnits = [.useKB, .useMB, .useGB]
        f.countStyle = .file
        return f.string(fromByteCount: totalSize)
    }
}
