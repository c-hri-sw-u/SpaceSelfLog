import Foundation

// MARK: - FrameScore

/// Per-frame importance scores across four independent dimensions, plus a weighted total.
struct FrameScore {
    let visual:   Float   // sharpness              (0–1)
    let audio:    Float   // audio state / change   (0–1)
    let imu:      Float   // motion state / change  (0–1)
    let sparsity: Float   // temporal spread        (0–1)
    let total:    Float   // weighted composite     (0–1)

    // Dimension weights (must sum to 1.0)
    private static let wVisual:   Float = 0.30
    private static let wAudio:    Float = 0.30
    private static let wIMU:      Float = 0.20
    private static let wSparsity: Float = 0.20

    init(visual: Float, audio: Float, imu: Float, sparsity: Float) {
        self.visual   = visual
        self.audio    = audio
        self.imu      = imu
        self.sparsity = sparsity
        self.total    = FrameScore.wVisual   * visual
                      + FrameScore.wAudio    * audio
                      + FrameScore.wIMU      * imu
                      + FrameScore.wSparsity * sparsity
    }
}

// MARK: - ImportanceScorer

/// Scores a frame on four axes and returns a composite FrameScore.
///
/// Audio and IMU sub-scores are **change-aware**: a frame where the sensor state
/// transitioned scores higher than a frame in a sustained state, which in turn
/// scores higher than a sustained boring state (quiet / stationary).
enum ImportanceScorer {

    /// Score a single frame.
    ///
    /// - Parameters:
    ///   - jpegData: Raw JPEG bytes of the frame.
    ///   - audioTags: Current frame's tag dict from AudioManager.
    ///   - imuTags: Current frame's tag dict from IMUManager.
    ///   - previousAudioTags: Previous surviving frame's audio tags, or nil for the first frame.
    ///   - previousIMUTags: Previous surviving frame's IMU tags, or nil for the first frame.
    ///   - timeSinceLastSelected: Seconds since the previous surviving frame (for sparsity).
    ///   - inheritedVADOnset: True if a deleted predecessor frame had a speech-onset event.
    ///   - inheritedVADOffset: True if a deleted predecessor frame had a speech-offset event.
    ///   - inheritedIMUTransition: True if a deleted predecessor frame had a motion-state change.
    static func score(
        jpegData: Data,
        audioTags: [String: Any],
        imuTags: [String: Any],
        previousAudioTags: [String: Any]?,
        previousIMUTags: [String: Any]?,
        timeSinceLastSelected: TimeInterval,
        inheritedVADOnset: Bool = false,
        inheritedVADOffset: Bool = false,
        inheritedIMUTransition: Bool = false
    ) -> FrameScore {
        FrameScore(
            visual:   visualScore(jpegData),
            audio:    audioScore(audioTags, previous: previousAudioTags,
                                 inheritedOnset: inheritedVADOnset,
                                 inheritedOffset: inheritedVADOffset),
            imu:      imuScore(imuTags, previous: previousIMUTags,
                               inheritedTransition: inheritedIMUTransition),
            sparsity: sparsityScore(timeSinceLastSelected)
        )
    }

    // MARK: - Sub-scores

    /// Sharpness score derived from Laplacian variance.
    /// variance < 50  → ~0.05 (blurry but survived filter)
    /// variance = 300 → ~0.56
    /// variance ≥ 500 → 1.0
    private static func visualScore(_ data: Data) -> Float {
        let v = FrameAnalysis.laplacianVariance(data)
        return min(1.0, max(0.05, (v - 50) / 450))
    }

    /// Audio activity score — change-aware, with inherited trigger support.
    ///
    /// Priority:
    ///   1. Inherited onset from a deleted predecessor   → 0.95
    ///   2. Inherited offset from a deleted predecessor  → 0.85
    ///   3. Speech onset detected vs. previous survivor  → 0.95
    ///   4. Speech offset detected vs. previous survivor → 0.85
    ///   5. Noise level changed (no speech transition)   → 0.50
    ///   6. Sustained speech                             → 0.55
    ///   7. Sustained loud / moderate / quiet            → 0.35 / 0.25 / 0.10
    private static func audioScore(
        _ tags: [String: Any],
        previous: [String: Any]?,
        inheritedOnset: Bool,
        inheritedOffset: Bool
    ) -> Float {
        // Inherited trigger takes highest priority.
        if inheritedOnset  { return 0.95 }
        if inheritedOffset { return 0.85 }

        let speech     = tags["speech_detected"] as? Bool   ?? false
        let noiseLevel = tags["noise_level"]     as? String ?? "quiet"

        if let prev = previous {
            let prevSpeech = prev["speech_detected"] as? Bool   ?? speech
            let prevNoise  = prev["noise_level"]     as? String ?? noiseLevel

            if speech != prevSpeech {
                return speech ? 0.95 : 0.85    // onset / offset
            }
            if noiseLevel != prevNoise {
                return 0.50                     // noise level shifted, no speech change
            }
        }

        // Sustained state (or first frame — no previous to compare)
        if speech { return 0.55 }
        switch noiseLevel {
        case "loud":     return 0.35
        case "moderate": return 0.25
        default:         return 0.10
        }
    }

    /// IMU motion score — change-aware, with inherited trigger support.
    ///
    ///   Inherited transition from a deleted predecessor → 0.90
    ///   State transition detected vs. previous survivor → 0.90
    ///   Sustained sustained_motion                      → 0.50
    ///   Sustained stationary                            → 0.15
    private static func imuScore(
        _ tags: [String: Any],
        previous: [String: Any]?,
        inheritedTransition: Bool
    ) -> Float {
        if inheritedTransition { return 0.90 }

        let state = tags["motion_state"] as? String ?? "stationary"

        if let prev = previous {
            let prevState = prev["motion_state"] as? String ?? state
            if state != prevState { return 0.90 }
        }

        return state == "sustained_motion" ? 0.50 : 0.15
    }

    /// Temporal sparsity score.
    /// Reaches 1.0 after 5 minutes (300 s) since the previous surviving frame.
    private static func sparsityScore(_ seconds: TimeInterval) -> Float {
        Float(min(seconds / 300.0, 1.0))
    }
}
