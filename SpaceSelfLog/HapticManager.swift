import UIKit

final class HapticManager {
    static func single() {
        let generator = UIImpactFeedbackGenerator(style: .heavy)
        generator.prepare()
        generator.impactOccurred()
    }

    static func double() {
        let generator = UIImpactFeedbackGenerator(style: .heavy)
        generator.prepare()
        generator.impactOccurred()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
            let generator2 = UIImpactFeedbackGenerator(style: .heavy)
            generator2.prepare()
            generator2.impactOccurred()
        }
    }
}