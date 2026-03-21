import Foundation
import CoreMotion

// MARK: - Motion State

enum MotionState: String, Codable {
    case stationary = "stationary"
    case sustained_motion = "sustained_motion"
}

// MARK: - IMUManager

/// IMU 1.3: raw CMAccelerometer → composite magnitude → rolling-window variance → binary motion state.
///
/// Logic:
/// - Window: 2.5 s at 50 Hz (125 samples)
/// - variance(window) < lowThreshold → "currently still"
/// - variance(window) > highThreshold, sustained for ≥ 6 s → sustained_motion
/// - variance drops below lowThreshold → back to stationary immediately
/// - Transient spikes (< 6 s of high variance) are ignored
///
/// Dual role:
/// - `onMotionStateChanged` fires on every transition so callers can
///   adjust capture interval or notify downstream layers.
/// - `currentMotionState` / `imuTags` provide the tag for frame metadata.
class IMUManager {
    // MARK: - Public interface

    private(set) var currentMotionState: MotionState = .stationary
    private var latestVariance: Double = 0.0

    /// Called on the main thread whenever the motion state transitions.
    var onMotionStateChanged: ((MotionState) -> Void)?

    /// Dictionary suitable for embedding in frame metadata / status responses.
    /// Thread-safe: reads are serialised through stateQueue.
    var imuTags: [String: Any] {
        var state: MotionState = .stationary
        var variance: Double = 0.0
        var elapsed: Double = 0.0
        let threshold = sustainedMotionThresholdSeconds
        stateQueue.sync {
            state = currentMotionState
            variance = latestVariance
            if let since = highVarianceSince {
                elapsed = min(Date().timeIntervalSince(since), threshold)
            }
        }
        return [
            "motion_state": state.rawValue,
            "variance": variance,
            "sustained_elapsed": elapsed,
            "sustained_threshold": threshold
        ]
    }

    // MARK: - Config

    private let sampleRateHz: Double = 50.0
    private let windowSeconds: Double = 2.5
    private var maxWindowSize: Int { Int(windowSeconds * sampleRateHz) } // 125

    /// Variance thresholds (units: g², raw accelerometer magnitude). Mutable for runtime tuning.
    var varianceHighThreshold: Double = 0.012
    var varianceLowThreshold: Double  = 0.006  // hysteresis gap

    /// Seconds of sustained high variance before declaring sustained_motion (5–8 s range).
    /// Mutable so callers can update it at runtime without restarting the sensor.
    var sustainedMotionThresholdSeconds: Double = 6.0

    // MARK: - Private state

    private let motionManager = CMMotionManager()
    private let processingQueue = OperationQueue()
    private let stateQueue = DispatchQueue(label: "IMUManager.state", qos: .userInitiated)

    private var magnitudeWindow: [Double] = []
    private var highVarianceSince: Date? = nil   // nil = not currently in high-variance
    // Accessed from both main thread (start/stop) and processingQueue (callback guard).
    // Protect with stateQueue to avoid Swift exclusive access abort.
    private var _isRunning = false
    private var isRunning: Bool {
        get { stateQueue.sync { _isRunning } }
        set { stateQueue.sync { self._isRunning = newValue } }
    }

    // CSV logging
    private var fileHandle: FileHandle?
    private let bufferQueue = DispatchQueue(label: "IMUManager.bufferSync", qos: .userInitiated)
    private var buffer: [String] = []
    private let bufferFlushCount = 50  // ~1 s at 50 Hz

    // MARK: - Start / Stop

    func start(dataDirectory: URL) {
        guard !isRunning else { return }

        let fileURL = dataDirectory.appendingPathComponent("imu_accelerometer.csv")
        ensureFileWithHeader(fileURL: fileURL)
        do {
            fileHandle = try FileHandle(forWritingTo: fileURL)
            fileHandle?.seekToEndOfFile()
        } catch {
            print("IMUManager: failed to open CSV: \(error)")
            return
        }

        processingQueue.name = "IMUManager.AccelerometerQueue"
        processingQueue.qualityOfService = .userInitiated

        motionManager.accelerometerUpdateInterval = 1.0 / sampleRateHz
        isRunning = true
        magnitudeWindow.removeAll()
        highVarianceSince = nil
        buffer.removeAll()

        motionManager.startAccelerometerUpdates(to: processingQueue) { [weak self] data, error in
            guard let self = self, self.isRunning else { return }
            if let d = data {
                self.processSample(d)
            } else if let e = error {
                print("IMUManager: accelerometer error: \(e)")
            }
        }
    }

    func stop() {
        guard isRunning else { return }
        isRunning = false
        motionManager.stopAccelerometerUpdates()
        flushBuffer()
        bufferQueue.sync {
            fileHandle?.closeFile()
            fileHandle = nil
        }
    }

    // MARK: - Sample processing

    private func processSample(_ data: CMAccelerometerData) {
        let t = Date()
        let ax = data.acceleration.x
        let ay = data.acceleration.y
        let az = data.acceleration.z
        let magnitude = (ax * ax + ay * ay + az * az).squareRoot()

        // --- Rolling window update ---
        stateQueue.sync {
            magnitudeWindow.append(magnitude)
            if magnitudeWindow.count > maxWindowSize {
                magnitudeWindow.removeFirst()
            }
        }

        // --- Variance & state machine (on stateQueue to serialise) ---
        stateQueue.async { [weak self] in
            guard let self = self else { return }
            self.updateMotionState(at: t)
        }

        // --- CSV logging ---
        let row = String(
            format: "%.6f,%.6f,%.6f,%.6f,%.6f\n",
            t.timeIntervalSinceReferenceDate,
            ax, ay, az,
            magnitude
        )
        bufferQueue.async { [weak self] in
            guard let self = self, self.isRunning else { return }
            self.buffer.append(row)
            if self.buffer.count >= self.bufferFlushCount {
                self.flushBufferLocked()
            }
        }
    }

    /// Called from stateQueue.
    private func updateMotionState(at timestamp: Date) {
        guard magnitudeWindow.count >= 2 else { return }

        let variance = computeVariance(magnitudeWindow)
        latestVariance = variance
        let previousState = currentMotionState

        if variance > varianceHighThreshold {
            // High variance — start or continue the sustained-motion clock
            if highVarianceSince == nil {
                highVarianceSince = timestamp
            }
            let elapsed = timestamp.timeIntervalSince(highVarianceSince!)
            if elapsed >= sustainedMotionThresholdSeconds {
                currentMotionState = .sustained_motion
            }
        } else if variance < varianceLowThreshold {
            // Low variance — reset clock and go stationary
            highVarianceSince = nil
            currentMotionState = .stationary
        }
        // Between thresholds (hysteresis zone): keep current state, don't reset clock

        if currentMotionState != previousState {
            let newState = currentMotionState
            DispatchQueue.main.async { [weak self] in
                self?.onMotionStateChanged?(newState)
            }
        }
    }

    // MARK: - Math

    private func computeVariance(_ values: [Double]) -> Double {
        guard values.count > 1 else { return 0 }
        let n = Double(values.count)
        let mean = values.reduce(0, +) / n
        let sumSq = values.reduce(0.0) { $0 + ($1 - mean) * ($1 - mean) }
        return sumSq / (n - 1)
    }

    // MARK: - CSV helpers

    private func ensureFileWithHeader(fileURL: URL) {
        guard !FileManager.default.fileExists(atPath: fileURL.path) else { return }
        let header = "timestamp,accelX,accelY,accelZ,magnitude\n"
        try? header.data(using: .utf8)?.write(to: fileURL)
    }

    private func flushBufferLocked() {
        guard let handle = fileHandle, !buffer.isEmpty else { return }
        let joined = buffer.joined()
        buffer.removeAll(keepingCapacity: true)
        if let data = joined.data(using: .utf8) {
            handle.write(data)
        }
    }

    private func flushBuffer() {
        bufferQueue.sync { flushBufferLocked() }
    }
}
