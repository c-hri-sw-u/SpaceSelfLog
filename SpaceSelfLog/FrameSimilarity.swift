import Foundation
import Vision

/// Computes perceptual similarity between two JPEG frames using Vision's
/// neural image feature print (VNGenerateImageFeaturePrintRequest), which
/// is powered by a MobileNet-family backbone.
///
/// The public API is identical to the old SSIM-based implementation:
/// `similarity(_:_:)` returns a value in [0, 1] where 1 = identical.
///
/// **Threshold calibration note:**
/// VNFeaturePrint distances are in a different range than SSIM scores.
/// Empirically, same-scene frames give distance ≈ 0.05–0.35 (similarity ≈ 0.65–0.95)
/// and clearly different scenes give distance ≈ 0.7–1.4+ (similarity ≈ 0 clamped).
/// Recommended starting point for ssimBoundaryThreshold: 0.50–0.60
/// (vs. 0.75–0.85 for the old SSIM).
enum FrameSimilarity {

    /// Returns a similarity score in [0, 1].
    /// 0 = completely different; 1 = identical.
    /// Returns 0 if either image cannot be processed.
    static func similarity(_ a: Data, _ b: Data) -> Float {
        guard let fa = featurePrint(a), let fb = featurePrint(b) else { return 0 }
        var distance: Float = 0
        try? fa.computeDistance(&distance, to: fb)
        return max(0, 1.0 - distance)
    }

    // MARK: - Private

    private static func featurePrint(_ jpegData: Data) -> VNFeaturePrintObservation? {
        let request = VNGenerateImageFeaturePrintRequest()
        request.imageCropAndScaleOption = .centerCrop
        let handler = VNImageRequestHandler(data: jpegData, options: [:])
        try? handler.perform([request])
        return request.results?.first as? VNFeaturePrintObservation
    }
}
