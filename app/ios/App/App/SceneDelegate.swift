import UIKit
import Capacitor

class SceneDelegate: UIResponder, UIWindowSceneDelegate {
    var window: UIWindow?

    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options connectionOptions: UIScene.ConnectionOptions) {
        guard let windowScene = scene as? UIWindowScene else { return }

        window = UIWindow(windowScene: windowScene)
        window?.rootViewController = MainViewController()
        window?.makeKeyAndVisible()

        SceneDelegateProxy.shared.scene(scene, willConnectTo: session, options: connectionOptions)
    }

    func scene(_ scene: UIScene, openURLContexts URLContexts: Set<UIOpenURLContext>) {
        SceneDelegateProxy.shared.scene(scene, openURLContexts: URLContexts)
    }

    func scene(_ scene: UIScene, continue userActivity: NSUserActivity) {
        SceneDelegateProxy.shared.scene(scene, continue: userActivity)
    }
}

/// 앱 화면(웹뷰). 디자인 규칙 '스토어 출시':
/// - 가장자리 스와이프로 뒤로 가기(웹 방문 기록 = 화면 이동, popstate)
/// - 첫 화면을 그리기 전 바탕을 런치 화면과 같은 색(LaunchBackground, 라이트·다크)으로 둬서 흰 화면이 번쩍이지 않게
class MainViewController: CAPBridgeViewController {
    override func capacitorDidLoad() {
        super.capacitorDidLoad()
        let background = UIColor(named: "LaunchBackground")
        view.backgroundColor = background
        webView?.isOpaque = false
        webView?.backgroundColor = background
        webView?.scrollView.backgroundColor = background
        webView?.allowsBackForwardNavigationGestures = true
    }
}
