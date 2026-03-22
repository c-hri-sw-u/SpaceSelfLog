import Foundation
import UIKit

// MARK: - Data types

/// A single frame held in the pre-batch buffer.
struct BufferedFrame {
    let id: Int
    let capturedAt: Date
    let jpegData: Data
    let audioTags: [String: Any]
    let imuTags: [String: Any]
    let currentInterval: Int
}

/// Trigger events accumulated from deleted (black/blurry) frames to pass to the next survivor.
struct PendingTriggers {
    var imuTransition: Bool = false
    var vadOnset:      Bool = false
    var vadOffset:     Bool = false

    var hasAny: Bool { imuTransition || vadOnset || vadOffset }

    mutating func merge(_ other: PendingTriggers) {
        imuTransition = imuTransition || other.imuTransition
        vadOnset      = vadOnset      || other.vadOnset
        vadOffset     = vadOffset     || other.vadOffset
    }
}

/// A surviving frame annotated with any trigger events inherited from adjacent deleted frames.
struct AnnotatedFrame {
    let frame:             BufferedFrame
    let inheritedTriggers: PendingTriggers
}

/// A frame that survived filtering and was selected for the outbox.
struct OutputFrame {
    let originalId: Int       // frameIdCounter value at capture time
    let capturedAt: Date
    let jpegData: Data
    let audioTags: [String: Any]
    let imuTags: [String: Any]
    let currentInterval: Int
    let score: FrameScore
}

/// A fully processed batch, ready to hand to OutboxManager.
struct ProcessedBatch {
    let batchId: String
    let sessionDirectory: URL
    let frames: [OutputFrame]
    let createdAt: Date
    let inputFrameCount: Int   // frames ingested before any filtering
}

/// Debug snapshot of the most recent SSIM boundary comparison.
struct SSIMComparisonData {
    let referenceJpeg: Data   // ~200px-wide thumbnail
    let incomingJpeg: Data
    let ssimValue: Float
    let didCut: Bool
    let timestamp: Date
}

// MARK: - BatchProcessor

/// Layer 1.5 — accumulates raw frames from FramePipeline, cuts batches on scene change or
/// time-out, then filters and scores them before passing top-K to the outbox.
///
/// Threading: `ingest()` may be called from any queue.
/// All internal state is serialised on `processingQueue`.
/// `onBatchReady` is called on `processingQueue`; callers should dispatch to main if needed.
final class BatchProcessor {

    // MARK: - Config (safe to write from main thread at any time)

    /// SSIM threshold for batch-boundary detection: similarity < this triggers a cut.
    var ssimBoundaryThreshold: Float = 0.75

    /// SSIM threshold for within-batch deduplication: similarity > this removes the later frame.
    var ssimDedupThreshold: Float = 0.92

    /// Max window for the first batch (no tail yet, no scene-change fallback).
    var firstBatchWindowSeconds: Double = 120.0

    /// Force-cut a batch after this many seconds even if no scene change is detected.
    var maxWindowSeconds: Double = 600.0

    /// Target frames per minute of batch duration (dynamic K scaling).
    var kDensityPerMin: Double = 1.0

    /// Minimum and maximum output frames per batch (bounds for dynamic K).
    var kMin: Int = 2
    var kMax: Int = 12

    /// Frames whose total score >= this threshold are always included ("guaranteed" set).
    /// Dynamic K then fills the remainder up to the computed target.
    var scoreThreshold: Float = 0.50

    // MARK: - Output

    /// Called on `processingQueue` when a processed batch is ready.
    var onBatchReady: ((ProcessedBatch) -> Void)?

    // MARK: - Observable state (written on processingQueue, read safely on any queue)

    private(set) var pendingFrameCount: Int = 0
    private(set) var lastBatchOutputCount: Int = 0
    private(set) var totalBatchesProcessed: Int = 0
    private(set) var lastBatchTime: Date? = nil
    private(set) var lastBatchTrigger: String = ""
    private(set) var lastSSIMComparison: SSIMComparisonData?

    var lastSSIMDebugDict: [String: Any]? {
        guard let c = lastSSIMComparison else { return nil }
        return [
            "referenceB64": c.referenceJpeg.base64EncodedString(),
            "incomingB64":  c.incomingJpeg.base64EncodedString(),
            "ssim":         c.ssimValue,
            "didCut":       c.didCut,
            "ts":           c.timestamp.timeIntervalSince1970
        ]
    }

    // MARK: - Private

    private var buffer: [BufferedFrame] = []
    private var lastBatchTailData: Data?     // last surviving frame of the previous batch
    private var batchStartTime: Date = Date()
    private var frameIdCounter: Int = 0
    private var lastSelectedAt: Date = .distantPast
    private var sessionDirectory: URL?

    private let processingQueue = DispatchQueue(label: "com.spaceselflog.batchprocessor", qos: .utility)

    // MARK: - Thumbnail helper (for SSIM debug display)

    private static func makeThumbnail(_ jpegData: Data, width: Int = 200) -> Data? {
        guard let src = UIImage(data: jpegData) else { return nil }
        let scale = CGFloat(width) / src.size.width
        let size = CGSize(width: CGFloat(width), height: src.size.height * scale)
        let renderer = UIGraphicsImageRenderer(size: size)
        return renderer.jpegData(withCompressionQuality: 0.55) { ctx in
            src.draw(in: CGRect(origin: .zero, size: size))
        }
    }

    // MARK: - Lifecycle

    func start(sessionDirectory: URL) {
        processingQueue.async { [weak self] in
            guard let self else { return }
            self.buffer = []
            self.lastBatchTailData = nil
            self.batchStartTime = Date()
            self.frameIdCounter = 0
            self.pendingFrameCount = 0
            self.lastBatchOutputCount = 0
            self.totalBatchesProcessed = 0
            self.lastBatchTime = nil
            self.lastBatchTrigger = ""
            self.lastSSIMComparison = nil
            self.lastSelectedAt = .distantPast
            self.sessionDirectory = sessionDirectory
            print("BatchProcessor: started — \(sessionDirectory.lastPathComponent)")
        }
    }

    /// Flush the current buffer as a final batch (called on stop/pause).
    func flush() {
        processingQueue.async { [weak self] in
            guard let self, !self.buffer.isEmpty else { return }
            self.cutBatch(reason: "flush")
        }
    }

    // MARK: - Ingestion

    /// Ingest a newly captured frame. Thread-safe; dispatches internally.
    func ingest(jpegData: Data, audioTags: [String: Any], imuTags: [String: Any], currentInterval: Int) {
        processingQueue.async { [weak self] in
            self?.ingestInternal(jpegData: jpegData, audioTags: audioTags,
                                 imuTags: imuTags, currentInterval: currentInterval)
        }
    }

    private func ingestInternal(
        jpegData: Data,
        audioTags: [String: Any],
        imuTags: [String: Any],
        currentInterval: Int
    ) {
        frameIdCounter += 1
        let frame = BufferedFrame(
            id: frameIdCounter,
            capturedAt: Date(),
            jpegData: jpegData,
            audioTags: audioTags,
            imuTags: imuTags,
            currentInterval: currentInterval
        )

        let elapsed = Date().timeIntervalSince(batchStartTime)
        let hasTail = lastBatchTailData != nil

        let windowLimit = hasTail ? maxWindowSeconds : firstBatchWindowSeconds
        if !buffer.isEmpty && elapsed >= windowLimit {
            cutBatch(reason: hasTail ? "max_window(\(Int(elapsed))s)" : "first_window(\(Int(elapsed))s)")
            buffer.append(frame)
        } else if hasTail {
            // After the first batch: check for scene change vs. the most recent frame
            // in the current buffer, falling back to the previous batch tail only when
            // the buffer is empty (i.e. the very first frame after a cut).
            // Using buffer.last prevents cascade cuts: once a scene-change cut fires,
            // subsequent frames compare against each other rather than the stale tail.
            let reference = buffer.last?.jpegData ?? lastBatchTailData!
            let sim = FrameSimilarity.similarity(jpegData, reference)
            let didCut = sim < ssimBoundaryThreshold
            lastSSIMComparison = SSIMComparisonData(
                referenceJpeg: Self.makeThumbnail(reference) ?? reference,
                incomingJpeg:  Self.makeThumbnail(jpegData)  ?? jpegData,
                ssimValue: sim,
                didCut: didCut,
                timestamp: Date()
            )
            if didCut {
                cutBatch(reason: String(format: "scene_change(ssim=%.3f)", sim))
            }
            buffer.append(frame)
        } else {
            // First batch, within max window — accumulate only.
            buffer.append(frame)
        }

        pendingFrameCount = buffer.count
    }

    // MARK: - Batch cutting

    private func cutBatch(reason: String) {
        guard !buffer.isEmpty else { return }
        let frames = buffer
        buffer = []
        batchStartTime = Date()
        lastBatchTrigger = reason
        print("BatchProcessor: cutting batch (reason=\(reason), input=\(frames.count))")
        processBatch(frames)
    }

    // MARK: - Batch processing pipeline

    private func processBatch(_ frames: [BufferedFrame]) {
        // 1 & 2. Black + blur filter with trigger-event inheritance.
        //        Deleted frames propagate their trigger events (IMU/VAD transitions)
        //        to the next surviving frame so scoring isn't blind to nearby events.
        let annotated = filterAndAnnotate(frames)
        guard !annotated.isEmpty else {
            print("BatchProcessor: batch dropped — all black/blurry frames")
            return
        }

        // 3. Save tail reference (last surviving frame for next batch's boundary SSIM)
        lastBatchTailData = annotated.last?.frame.jpegData

        // 4. Importance scoring (all surviving frames, with inherited triggers)
        var prevTime: Date = lastSelectedAt == .distantPast
            ? annotated[0].frame.capturedAt.addingTimeInterval(-300)
            : lastSelectedAt
        var prevAudioTags: [String: Any]? = nil
        var prevIMUTags:   [String: Any]? = nil

        let scored: [(AnnotatedFrame, FrameScore)] = annotated.map { af in
            let gap = max(0, af.frame.capturedAt.timeIntervalSince(prevTime))
            let s = ImportanceScorer.score(
                jpegData: af.frame.jpegData,
                audioTags: af.frame.audioTags,
                imuTags: af.frame.imuTags,
                previousAudioTags: prevAudioTags,
                previousIMUTags: prevIMUTags,
                timeSinceLastSelected: gap,
                inheritedVADOnset: af.inheritedTriggers.vadOnset,
                inheritedVADOffset: af.inheritedTriggers.vadOffset,
                inheritedIMUTransition: af.inheritedTriggers.imuTransition
            )
            prevTime      = af.frame.capturedAt
            prevAudioTags = af.frame.audioTags
            prevIMUTags   = af.frame.imuTags
            return (af, s)
        }

        // 5. Sort by score desc, then greedy dedup: highest-scored frame wins ties.
        let sortedByScore = scored.sorted { $0.1.total > $1.1.total }
        let deduped = deduplicateByScore(sortedByScore)

        // 6. Dynamic K: scale with batch duration, bounded by kMin/kMax.
        let batchDurationMin: Double = {
            guard let first = annotated.first, let last = annotated.last else { return 0 }
            return max(0, last.frame.capturedAt.timeIntervalSince(first.frame.capturedAt)) / 60.0
        }()
        let kDynamic = max(kMin, min(kMax, Int((batchDurationMin * kDensityPerMin).rounded(.up))))

        // 7. Guaranteed set: all deduped frames above the score threshold (多不退).
        //    Fill up to kDynamic from the remaining lower-score frames (少补).
        let guaranteed = deduped.filter { $0.1.total >= scoreThreshold }
        let remaining  = deduped.filter { $0.1.total <  scoreThreshold }
        let topK: [(AnnotatedFrame, FrameScore)]
        if guaranteed.count >= kDynamic {
            topK = guaranteed
        } else {
            topK = guaranteed + Array(remaining.prefix(kDynamic - guaranteed.count))
        }
        guard !topK.isEmpty else { return }

        lastSelectedAt = Date()
        lastBatchTime = Date()
        lastBatchOutputCount = topK.count
        totalBatchesProcessed += 1

        let outputFrames = topK.map { (af, score) in
            OutputFrame(
                originalId: af.frame.id,
                capturedAt: af.frame.capturedAt,
                jpegData: af.frame.jpegData,
                audioTags: af.frame.audioTags,
                imuTags: af.frame.imuTags,
                currentInterval: af.frame.currentInterval,
                score: score
            )
        }

        guard let dir = sessionDirectory else { return }

        let batchId = Date().formatted(.iso8601)
            .replacingOccurrences(of: ":", with: "-")

        let batch = ProcessedBatch(
            batchId: batchId,
            sessionDirectory: dir,
            frames: outputFrames,
            createdAt: Date(),
            inputFrameCount: frames.count
        )

        print("BatchProcessor: batch ready — selected \(topK.count)/\(frames.count) " +
              "(survived: \(annotated.count), deduped: \(deduped.count), " +
              "guaranteed: \(guaranteed.count), kDynamic: \(kDynamic), " +
              String(format: "duration: %.1fmin)", batchDurationMin))

        onBatchReady?(batch)
    }

    // MARK: - Filter + trigger-event inheritance

    /// Combines black and blur filtering with trigger-event propagation.
    ///
    /// Scans frames in chronological order; when a frame is deleted, its trigger events
    /// (IMU transition, VAD onset/offset — detected relative to the immediately preceding
    /// frame) are accumulated. The first surviving frame after a run of deleted frames
    /// inherits all accumulated triggers so scoring can reflect nearby events.
    ///
    /// Only trigger events are inherited; ordinary state tags (speech_detected, motion_state,
    /// noise_level) are not — those describe the deleted frame's own state, not the survivor's.
    private func filterAndAnnotate(_ frames: [BufferedFrame]) -> [AnnotatedFrame] {
        var result: [AnnotatedFrame] = []
        var prevAudio: [String: Any]? = nil
        var prevIMU:   [String: Any]? = nil
        var pending    = PendingTriggers()

        for frame in frames {
            // Detect trigger events relative to the immediately preceding frame
            // (regardless of whether it was deleted or survived).
            if let pAudio = prevAudio, let pIMU = prevIMU {
                let prevSpeech = pAudio["speech_detected"] as? Bool   ?? false
                let curSpeech  = frame.audioTags["speech_detected"] as? Bool   ?? false
                if curSpeech != prevSpeech {
                    if curSpeech { pending.vadOnset  = true }
                    else         { pending.vadOffset = true }
                }

                let prevMotion = pIMU["motion_state"]  as? String ?? "stationary"
                let curMotion  = frame.imuTags["motion_state"] as? String ?? "stationary"
                if curMotion != prevMotion { pending.imuTransition = true }
            }

            prevAudio = frame.audioTags
            prevIMU   = frame.imuTags

            // Apply black and blur filters.
            if FrameAnalysis.isBlackFrame(frame.jpegData) || FrameAnalysis.isBlurry(frame.jpegData) {
                // Triggers already captured above; carry them forward.
                continue
            }

            // Frame survives — attach all accumulated triggers and reset.
            result.append(AnnotatedFrame(frame: frame, inheritedTriggers: pending))
            pending = PendingTriggers()
        }

        return result
    }

    // MARK: - Score-aware deduplication

    /// Greedy dedup on a score-descending list.
    /// Iterates from highest to lowest score; drops a frame if any already-kept frame
    /// is too similar (SSIM > ssimDedupThreshold). This guarantees the highest-quality
    /// representative survives when near-duplicates compete.
    private func deduplicateByScore(_ sortedDesc: [(AnnotatedFrame, FrameScore)]) -> [(AnnotatedFrame, FrameScore)] {
        var kept: [(AnnotatedFrame, FrameScore)] = []
        for item in sortedDesc {
            let isDuplicate = kept.contains {
                FrameSimilarity.similarity(item.0.frame.jpegData, $0.0.frame.jpegData) > ssimDedupThreshold
            }
            if !isDuplicate { kept.append(item) }
        }
        return kept
    }
}
