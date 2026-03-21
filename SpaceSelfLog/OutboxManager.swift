import Foundation

// MARK: - OutboxEntry (persisted)

private struct OutboxEntry: Codable {
    let entryId: String
    let batchId: String
    let sessionId: String
    let enqueuedAt: Date
    let frameCount: Int
    var retryCount: Int
    var nextRetryAt: Date
    let dataURL: URL          // absolute path to the on-disk batch directory
}

// MARK: - OutboxManager

/// Persists processed batches to a local outbox directory and uploads them to a
/// configurable HTTP endpoint (e.g. a Tailscale host).
///
/// Upload format: JSON body containing a manifest and per-frame base64-encoded JPEGs.
/// On failure the entry is re-queued with exponential back-off (cap: 64 s, max: 10 retries).
///
/// Threading: `enqueue()` is safe to call from any queue.
/// All mutable state is serialised on `drainQueue`.
/// Published properties (`queueSize`, `lastUploadStatus`, etc.) are updated on the main thread.
final class OutboxManager {

    // MARK: - Config

    /// Upload endpoint URL. Set to nil to disable uploads (frames accumulate locally).
    var uploadEndpoint: URL?

    // MARK: - Observable state (main-thread safe to read)

    private(set) var queueSize: Int = 0
    private(set) var lastUploadAt: Date?
    private(set) var lastUploadStatus: String = "idle"
    private(set) var failureCount: Int = 0

    // MARK: - Private

    private var outboxDirectory: URL?
    private var entries: [OutboxEntry] = []
    private var drainTimer: Timer?

    private let drainQueue = DispatchQueue(label: "com.spaceselflog.outbox", qos: .utility)
    private let maxRetries = 10
    private let maxBackoffSeconds: Double = 64.0

    private let iso8601: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    // MARK: - Lifecycle

    func start(sessionDirectory: URL) {
        let dir = sessionDirectory.appendingPathComponent("outbox")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        outboxDirectory = dir

        drainQueue.async { [weak self] in
            guard let self else { return }
            self.entries = self.loadPersistedEntries()
            DispatchQueue.main.async { self.queueSize = self.entries.count }
        }

        startDrainTimer()
        print("OutboxManager: started — \(dir.path)")
    }

    func stop() {
        drainTimer?.invalidate()
        drainTimer = nil
    }

    // MARK: - Enqueue

    func enqueue(batch: ProcessedBatch) {
        drainQueue.async { [weak self] in
            self?.enqueueInternal(batch: batch)
        }
    }

    private func enqueueInternal(batch: ProcessedBatch) {
        guard let outboxDir = outboxDirectory else { return }

        let entryId = UUID().uuidString
        let dataDir = outboxDir.appendingPathComponent(batch.batchId)
        try? FileManager.default.createDirectory(at: dataDir, withIntermediateDirectories: true)

        // Write each selected frame as an individual JPEG, sorted by capture time.
        // Filename: {time_index:02d}_{originalId:05d}.jpg
        let sortedFrames = batch.frames.sorted { $0.capturedAt < $1.capturedAt }
        for (i, frame) in sortedFrames.enumerated() {
            let name = String(format: "%02d_%05d.jpg", i, frame.originalId)
            try? frame.jpegData.write(to: dataDir.appendingPathComponent(name))
        }

        // Write human-readable manifest (no binary data here).
        let manifest = buildManifest(batch: batch, entryId: entryId)
        if let data = try? JSONSerialization.data(withJSONObject: manifest, options: .prettyPrinted) {
            try? data.write(to: dataDir.appendingPathComponent("manifest.json"))
        }

        let entry = OutboxEntry(
            entryId: entryId,
            batchId: batch.batchId,
            sessionId: batch.sessionDirectory.lastPathComponent,
            enqueuedAt: Date(),
            frameCount: batch.frames.count,
            retryCount: 0,
            nextRetryAt: Date(),
            dataURL: dataDir
        )
        entries.append(entry)
        persistEntries()

        DispatchQueue.main.async { self.queueSize = self.entries.count }
        print("OutboxManager: enqueued \(batch.batchId) (\(batch.frames.count) frames)")
    }

    // MARK: - Drain loop

    private func startDrainTimer() {
        DispatchQueue.main.async { [weak self] in
            self?.drainTimer = Timer.scheduledTimer(
                withTimeInterval: 30.0, repeats: true
            ) { [weak self] _ in
                self?.drainQueue.async { self?.drainOnce() }
            }
        }
    }

    private func drainOnce() {
        guard let endpoint = uploadEndpoint else { return }

        let now = Date()
        let due = entries.filter { $0.nextRetryAt <= now && $0.retryCount < maxRetries }
        guard !due.isEmpty else { return }

        for var entry in due {
            do {
                try uploadSync(entry: entry, endpoint: endpoint)
                removeEntry(entry)
                DispatchQueue.main.async {
                    self.lastUploadAt = Date()
                    self.lastUploadStatus = "ok"
                    self.queueSize = self.entries.count
                }
                print("OutboxManager: uploaded \(entry.batchId)")
            } catch {
                entry.retryCount += 1
                let backoff = min(pow(2.0, Double(entry.retryCount)), maxBackoffSeconds)
                entry.nextRetryAt = Date().addingTimeInterval(backoff)
                updateEntry(entry)
                DispatchQueue.main.async {
                    self.failureCount += 1
                    self.lastUploadStatus = "error(\(entry.retryCount)): \(error.localizedDescription)"
                }
                print("OutboxManager: upload failed retry \(entry.retryCount)/\(maxRetries): \(error)")
            }
        }

        // Drop entries that have exhausted all retries.
        let exhausted = entries.filter { $0.retryCount >= maxRetries }
        for entry in exhausted {
            print("OutboxManager: dropping \(entry.entryId) after \(maxRetries) retries")
            removeEntry(entry)
        }

        DispatchQueue.main.async { self.queueSize = self.entries.count }
    }

    // MARK: - HTTP upload (synchronous, called on drainQueue)

    private func uploadSync(entry: OutboxEntry, endpoint: URL) throws {
        // Build manifest + inline base64 frames.
        guard
            let manifestData = try? Data(contentsOf: entry.dataURL.appendingPathComponent("manifest.json")),
            var manifest = try? JSONSerialization.jsonObject(with: manifestData) as? [String: Any]
        else { throw URLError(.badURL) }

        let jpegURLs = (try? FileManager.default.contentsOfDirectory(
            at: entry.dataURL,
            includingPropertiesForKeys: nil
        ).filter { $0.pathExtension == "jpg" }
         .sorted { $0.lastPathComponent < $1.lastPathComponent }) ?? []

        manifest["frames"] = jpegURLs.compactMap { url -> [String: Any]? in
            guard let data = try? Data(contentsOf: url) else { return nil }
            return ["filename": url.lastPathComponent, "jpeg_base64": data.base64EncodedString()]
        }

        guard let body = try? JSONSerialization.data(withJSONObject: manifest) else {
            throw URLError(.cannotDecodeContentData)
        }

        var request = URLRequest(url: endpoint, timeoutInterval: 60)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = body

        var uploadError: Error?
        let semaphore = DispatchSemaphore(value: 0)
        URLSession.shared.dataTask(with: request) { _, response, error in
            if let error {
                uploadError = error
            } else if let http = response as? HTTPURLResponse, http.statusCode >= 400 {
                uploadError = URLError(.badServerResponse)
            }
            semaphore.signal()
        }.resume()
        semaphore.wait()

        if let err = uploadError { throw err }
    }

    // MARK: - Entry helpers

    private func removeEntry(_ entry: OutboxEntry) {
        entries.removeAll { $0.entryId == entry.entryId }
        try? FileManager.default.removeItem(at: entry.dataURL)
        persistEntries()
    }

    private func updateEntry(_ entry: OutboxEntry) {
        if let idx = entries.firstIndex(where: { $0.entryId == entry.entryId }) {
            entries[idx] = entry
        }
        persistEntries()
    }

    private func persistEntries() {
        guard let dir = outboxDirectory else { return }
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        if let data = try? encoder.encode(entries) {
            try? data.write(to: dir.appendingPathComponent("queue.json"))
        }
    }

    private func loadPersistedEntries() -> [OutboxEntry] {
        guard let dir = outboxDirectory else { return [] }
        let url = dir.appendingPathComponent("queue.json")
        guard let data = try? Data(contentsOf: url) else { return [] }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return (try? decoder.decode([OutboxEntry].self, from: data)) ?? []
    }

    // MARK: - Manifest builder

    private func buildManifest(batch: ProcessedBatch, entryId: String) -> [String: Any] {
        [
            "entry_id":     entryId,
            "batch_id":     batch.batchId,
            "session_id":   batch.sessionDirectory.lastPathComponent,
            "created_at":   iso8601.string(from: batch.createdAt),
            "frame_count":  batch.frames.count,
            "input_frames": batch.inputFrameCount,
            "frames_meta":  batch.frames.sorted { $0.capturedAt < $1.capturedAt }
                .enumerated().map { (i, frame) -> [String: Any] in
                [
                    "index":            i,
                    "original_id":      frame.originalId,
                    "filename":         String(format: "%02d_%05d.jpg", i, frame.originalId),
                    "captured_at":      iso8601.string(from: frame.capturedAt),
                    "current_interval": frame.currentInterval,
                    "audio_tags":       frame.audioTags,
                    "imu_tags":         frame.imuTags,
                    "score_visual":     frame.score.visual,
                    "score_audio":      frame.score.audio,
                    "score_imu":        frame.score.imu,
                    "score_sparsity":   frame.score.sparsity,
                    "score_total":      frame.score.total
                ]
            }
        ]
    }
}
