import Foundation
import UIKit

// MARK: - OpenRouter API Service
final class OpenRouterAPIService {
    enum APIError: Error, LocalizedError {
        case invalidURL
        case invalidAPIKey
        case noResponse
        case invalidResponse
        case networkError(Error)
        case apiError(String)

        var errorDescription: String? {
            switch self {
            case .invalidURL:
                return "Invalid API URL"
            case .invalidAPIKey:
                return "Invalid API Key"
            case .noResponse:
                return "No response received"
            case .invalidResponse:
                return "Invalid response format"
            case .networkError(let error):
                return "Network error: \(error.localizedDescription)"
            case .apiError(let message):
                return "API error: \(message)"
            }
        }
    }

    private let session = URLSession.shared
    private let baseURL = URL(string: "https://openrouter.ai/api/v1/chat/completions")

    struct ORMessageImageURL: Codable {
        let url: String
        let detail: String?
    }

    struct ORMessageContentPart: Codable {
        let type: String
        let text: String?
        let image_url: ORMessageImageURL?
    }

    struct ORMessage: Codable {
        let role: String
        let content: [ORMessageContentPart]
    }

    struct ORRequest: Codable {
        let model: String
        let messages: [ORMessage]
        let user: String?
    }

    struct ORChoiceMessage: Codable {
        let role: String?
        let content: String?
    }

    struct ORChoice: Codable {
        let message: ORChoiceMessage?
    }

    struct ORResponse: Codable {
        let choices: [ORChoice]?
        let error: String?
    }

    // Analyze an image using OpenRouter with a preset slug
    func analyzeImage(imageData: Data, prompt: String, apiKey: String, presetSlug: String, userId: String? = nil, completion: @escaping (Result<String, APIError>) -> Void) {
        guard !apiKey.isEmpty else {
            completion(.failure(.invalidAPIKey))
            return
        }
        guard let baseURL = baseURL else {
            completion(.failure(.invalidURL))
            return
        }

        var urlRequest = URLRequest(url: baseURL)
        urlRequest.httpMethod = "POST"
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        urlRequest.setValue("Bearer \(apiKey)", forHTTPHeaderField: "Authorization")

        let imageBase64 = imageData.base64EncodedString()
        let imageContent = ORMessageContentPart(type: "image_url", text: nil, image_url: ORMessageImageURL(url: "data:image/jpeg;base64,\(imageBase64)", detail: "auto"))
        let textContent = ORMessageContentPart(type: "text", text: prompt, image_url: nil)
        let message = ORMessage(role: "user", content: [textContent, imageContent])

        let requestBody = ORRequest(model: "@preset/\(presetSlug)", messages: [message], user: userId)

        do {
            urlRequest.httpBody = try JSONEncoder().encode(requestBody)
        } catch {
            completion(.failure(.networkError(error)))
            return
        }

        session.dataTask(with: urlRequest) { data, response, error in
            if let error = error {
                completion(.failure(.networkError(error)))
                return
            }
            guard let data = data else {
                completion(.failure(.noResponse))
                return
            }

            // Check HTTP status
            if let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode != 200 {
                if let errorString = String(data: data, encoding: .utf8) {
                    completion(.failure(.apiError("HTTP \(httpResponse.statusCode): \(errorString)")))
                } else {
                    completion(.failure(.apiError("HTTP \(httpResponse.statusCode)")))
                }
                return
            }

            do {
                let orResponse = try JSONDecoder().decode(ORResponse.self, from: data)
                if let content = orResponse.choices?.first?.message?.content, !content.isEmpty {
                    completion(.success(content))
                } else {
                    completion(.failure(.invalidResponse))
                }
            } catch {
                completion(.failure(.networkError(error)))
            }
        }.resume()
    }

    // Simple API key test by sending a 1x1 white image
    func testAPIKey(_ apiKey: String, presetSlug: String, completion: @escaping (Result<Void, APIError>) -> Void) {
        let testImageData = createTestImage()
        analyzeImage(imageData: testImageData, prompt: "What do you see?", apiKey: apiKey, presetSlug: presetSlug) { result in
            switch result {
            case .success:
                completion(.success(()))
            case .failure(let error):
                completion(.failure(error))
            }
        }
    }

    private func createTestImage() -> Data {
        // Create 1x1 white JPEG
        let renderer = UIGraphicsImageRenderer(size: CGSize(width: 1, height: 1))
        let image = renderer.image { ctx in
            UIColor.white.setFill()
            ctx.fill(CGRect(x: 0, y: 0, width: 1, height: 1))
        }
        return image.jpegData(compressionQuality: 1.0) ?? Data()
    }
}