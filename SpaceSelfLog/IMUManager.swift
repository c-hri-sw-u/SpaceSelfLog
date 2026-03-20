import Foundation
import CoreMotion

class IMUManager {
    private let motionManager = CMMotionManager()
    private var fileHandle: FileHandle?
    private let queue = OperationQueue()
    private let bufferQueue = DispatchQueue(label: "IMUManager.bufferSync", qos: .userInitiated)
    private var buffer: [String] = []
    private let bufferFlushCount = 50 // ~1s at 50Hz
    private var isRunning = false
    private var csvURL: URL?

    func start(dataDirectory: URL, frequencyHz: Double = 50.0) {
        guard !isRunning else { return }

        let fileURL = dataDirectory.appendingPathComponent("imu_readings.csv")
        csvURL = fileURL
        ensureFileWithHeader(fileURL: fileURL)

        do {
            fileHandle = try FileHandle(forWritingTo: fileURL)
            fileHandle?.seekToEndOfFile()
        } catch {
            print("IMUManager: failed to open CSV file for writing: \(error)")
            return
        }

        queue.name = "IMUManager.DeviceMotionQueue"
        queue.qualityOfService = .userInitiated

        motionManager.deviceMotionUpdateInterval = 1.0 / frequencyHz
        isRunning = true
        buffer.removeAll()

        motionManager.startDeviceMotionUpdates(to: queue) { [weak self] motion, error in
            guard let self = self else { return }
            if let m = motion {
                let t = Date().timeIntervalSinceReferenceDate
                let ua = m.userAcceleration
                let rr = m.rotationRate
                let g = m.gravity
                let att = m.attitude

                let row = String(
                    format: "%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f\n",
                    t,
                    ua.x, ua.y, ua.z,
                    rr.x, rr.y, rr.z,
                    g.x, g.y, g.z,
                    att.roll, att.pitch, att.yaw
                )

                // Guard against writes after stop and serialize buffer mutations
                guard self.isRunning else { return }
                self.bufferQueue.async {
                    self.buffer.append(row)
                    if self.buffer.count >= self.bufferFlushCount {
                        self.flushBufferLocked()
                    }
                }
            } else if let e = error {
                print("IMUManager: deviceMotion error: \(e)")
            }
        }
    }

    private func ensureFileWithHeader(fileURL: URL) {
        if !FileManager.default.fileExists(atPath: fileURL.path) {
            let header = "timestampRef,userAccX,userAccY,userAccZ,rotRateX,rotRateY,rotRateZ,gravityX,gravityY,gravityZ,roll,pitch,yaw\n"
            do {
                try header.data(using: .utf8)?.write(to: fileURL)
            } catch {
                print("IMUManager: failed to create CSV file: \(error)")
            }
        }
    }

    // Should be called inside bufferQueue
    private func flushBufferLocked() {
        guard let handle = fileHandle, !buffer.isEmpty else { return }
        let joined = buffer.joined()
        buffer.removeAll(keepingCapacity: true)
        if let data = joined.data(using: .utf8) {
            handle.write(data)
        }
    }

    private func flushBuffer() {
        bufferQueue.sync {
            flushBufferLocked()
        }
    }

    func stop() {
        guard isRunning else { return }
        // Mark stopped first so callbacks ignore
        isRunning = false
        motionManager.stopDeviceMotionUpdates()
        flushBuffer()
        fileQueueSafeClose()
    }

    private func fileQueueSafeClose() {
        bufferQueue.sync {
            fileHandle?.closeFile()
            fileHandle = nil
        }
    }
}
