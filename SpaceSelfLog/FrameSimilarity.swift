import Foundation
import UIKit

/// Computes perceptual similarity between two JPEG frames using a simplified SSIM
/// on 32 × 32 grayscale thumbnails.
enum FrameSimilarity {

    private static let side = 32

    /// Returns a similarity score in [0, 1].
    /// 0 = completely different; 1 = identical.
    /// Returns 0 if either image cannot be decoded.
    static func similarity(_ a: Data, _ b: Data) -> Float {
        guard
            let pa = FrameAnalysis.grayPixels(a, side: side),
            let pb = FrameAnalysis.grayPixels(b, side: side)
        else { return 0 }
        return ssim(pa, pb)
    }

    // MARK: - Simplified SSIM

    /// Single-scale SSIM on flat, equal-length arrays of pixel values (any range).
    /// C1 and C2 are tuned for a 0–255 range (the standard 8-bit constants).
    private static func ssim(_ x: [Float], _ y: [Float]) -> Float {
        guard x.count == y.count, !x.isEmpty else { return 0 }
        let n = Float(x.count)

        // Means
        let muX = x.reduce(0, +) / n
        let muY = y.reduce(0, +) / n

        // Variances and covariance
        var varX: Float = 0, varY: Float = 0, covXY: Float = 0
        for i in x.indices {
            let dx = x[i] - muX
            let dy = y[i] - muY
            varX  += dx * dx
            varY  += dy * dy
            covXY += dx * dy
        }
        varX  /= n
        varY  /= n
        covXY /= n

        // Standard 8-bit stabilising constants: (k·L)² where L=255, k1=0.01, k2=0.03
        let c1: Float = 6.5025    // (0.01·255)²
        let c2: Float = 58.5225   // (0.03·255)²

        let numerator   = (2 * muX * muY + c1) * (2 * covXY + c2)
        let denominator = (muX * muX + muY * muY + c1) * (varX + varY + c2)
        guard denominator > 0 else { return 1.0 }
        return max(0, min(1, numerator / denominator))
    }
}
