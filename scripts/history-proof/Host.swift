// A tiny native WKWebView host. No copied component or replacement scrollbar.
import AppKit
import WebKit
import Foundation

let app = NSApplication.shared
app.setActivationPolicy(.regular)
let config = WKWebViewConfiguration()
config.websiteDataStore = .nonPersistent()
config.userContentController.addUserScript(WKUserScript(source: "localStorage.setItem('dbx-locale', 'en');", injectionTime: .atDocumentStart, forMainFrameOnly: true))
let web = WKWebView(frame: NSRect(x: 0, y: 0, width: 1100, height: 740), configuration: config)
let window = NSWindow(contentRect: web.frame, styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
window.title = "DBX History regression — native WKWebView"
window.contentView = web
window.center()
window.makeKeyAndOrderFront(nil)
app.activate(ignoringOtherApps: true)

func reply(_ value: Any) {
    let object: [String: Any] = ["value": value]
    do {
        let data = try JSONSerialization.data(withJSONObject: object, options: [.fragmentsAllowed, .sortedKeys])
        FileHandle.standardOutput.write(data)
        FileHandle.standardOutput.write(Data([10]))
    } catch {
        FileHandle.standardOutput.write(Data("{\"error\":\"JSON serialization failed\"}\n".utf8))
    }
}

func point(_ command: [String: Any]) -> CGPoint {
    // DOM uses top-left coordinates; AppKit view/window coordinates use bottom-left.
    let x = command["x"] as? Double ?? 0
    let y = command["y"] as? Double ?? 0
    let inWindow = web.convert(NSPoint(x: x, y: web.bounds.height - y), to: nil)
    let inScreen = window.convertPoint(toScreen: inWindow)
    let screenHeight = NSScreen.screens.first!.frame.height
    return CGPoint(x: inScreen.x, y: screenHeight - inScreen.y)
}

func post(_ type: CGEventType, _ command: [String: Any]) {
    let event = CGEvent(mouseEventSource: nil, mouseType: type, mouseCursorPosition: point(command), mouseButton: .left)!
    event.postToPid(ProcessInfo.processInfo.processIdentifier)
}

DispatchQueue.global().async {
    while let line = readLine() {
        guard let data = line.data(using: .utf8), let command = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { continue }
        DispatchQueue.main.async {
            switch command["op"] as? String {
            case "load":
                web.load(URLRequest(url: URL(string: command["url"] as! String)!))
                reply(true)
            case "eval":
                web.evaluateJavaScript(command["script"] as! String) { value, error in
                    if let error = error { reply(["error": String(describing: error)]) }
                    else { reply(value ?? NSNull()) }
                }
            case "move": post(.mouseMoved, command); reply(true)
            case "down": post(.leftMouseDown, command); reply(true)
            case "drag": post(.leftMouseDragged, command); reply(true)
            case "up": post(.leftMouseUp, command); reply(true)
            case "click":
                post(.mouseMoved, command); post(.leftMouseDown, command); post(.leftMouseUp, command); reply(true)
            case "wheel":
                post(.mouseMoved, command)
                let event = CGEvent(scrollWheelEvent2Source: nil, units: .pixel, wheelCount: 2, wheel1: 0, wheel2: Int32(command["delta"] as? Int ?? -28), wheel3: 0)!
                event.location = point(command)
                event.postToPid(ProcessInfo.processInfo.processIdentifier)
                reply(true)
            case "info":
                reply(["window": window.windowNumber, "pid": ProcessInfo.processInfo.processIdentifier,
                       "width": web.bounds.width, "height": web.bounds.height,
                       "screenCaptureAllowed": CGPreflightScreenCaptureAccess()])
            case "quit": reply(true); app.terminate(nil)
            default: reply(["error": "Unknown operation"])
            }
        }
    }
}
app.run()
