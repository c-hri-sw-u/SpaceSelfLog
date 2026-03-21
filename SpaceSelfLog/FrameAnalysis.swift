import Foundation
import UIKit

/// Static utilities for per-frame quality analysis.
/// All functions accept raw JPEG bytes and return a scalar quality indicator.
enum FrameAnalysis {

    // MARK: - Black Frame

    /// Returns true if the frame's average luminance is below `threshold` (0–255 scale).
    /// Default threshold = 12.75 ≈ 5 % of full white.
    static func isBlackFrame(_ jpegData: Data, threshold: Float = 12.75) -> Bool {
        guard let pixels = grayPixels(jpegData, side: 64) else { return false }
        let mean = pixels.reduce(0, +) / Float(pixels.count)
        return mean < threshold
    }

    // MARK: - Blur (Laplacian variance)

    /// Computes the Laplacian variance of the image.
    /// Higher value = sharper. Typical ranges: blurry < 80, acceptable 80–300, sharp > 300.
    /// Pixel values are treated on a 0–255 scale, so the returned variance is in squared-pixel units.
    static func laplacianVariance(_ jpegData: Data) -> Float {
        guard let pixels = grayPixels(jpegData, side: 64) else { return 0 }
        let side = 64

        // Discrete Laplacian: L(i) = -4·p + up + down + left + right
        var lap: [Float] = []
        lap.reserveCapacity((side - 2) * (side - 2))
        for y in 1..<(side - 1) {
            for x in 1..<(side - 1) {
                let i = y * side + x
                let v = -4 * pixels[i]
                    + pixels[i - side]
                    + pixels[i + side]
                    + pixels[i - 1]
                    + pixels[i + 1]
                lap.append(v)
            }
        }

        // Variance = E[x²] − E[x]²
        let n = Float(lap.count)
        let mean = lap.reduce(0, +) / n
        let variance = lap.reduce(0) { $0 + ($1 - mean) * ($1 - mean) } / n
        return variance  // already in squared-pixel units (0–255 scale)
    }

    /// Returns true if the frame is considered too blurry to be useful.
    static func isBlurry(_ jpegData: Data, threshold: Float = 80.0) -> Bool {
        laplacianVariance(jpegData) < threshold
    }

    // MARK: - Internal

    /// Renders a JPEG to a `side × side` grayscale pixel buffer.
    /// Values are in the **0–255** range (Float), or nil on decode failure.
    static func grayPixels(_ jpegData: Data, side: Int) -> [Float]? {
        guard let image = UIImage(data: jpegData)?.cgImage else { return nil }

        var raw = [UInt8](repeating: 0, count: side * side)
        guard let ctx = CGContext(
            data: &raw,
            width: side, height: side,
            bitsPerComponent: 8,
            bytesPerRow: side,
            space: CGColorSpaceCreateDeviceGray(),
            bitmapInfo: CGImageAlphaInfo.none.rawValue
        ) else { return nil }

        ctx.draw(image, in: CGRect(x: 0, y: 0, width: side, height: side))
        return raw.map { Float($0) }
    }
}
