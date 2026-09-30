#include "flutter_window.h"

#include <optional>

#include <windows.h>
#include <shellapi.h>
#include "flutter/generated_plugin_registrant.h"

FlutterWindow::FlutterWindow(const flutter::DartProject& project)
    : project_(project) {}

FlutterWindow::~FlutterWindow() {}

bool FlutterWindow::OnCreate() {
  if (!Win32Window::OnCreate()) return false;

  RECT frame = GetClientArea();
  flutter_controller_ = std::make_unique<flutter::FlutterViewController>(
      frame.right - frame.left, frame.bottom - frame.top, project_);
  if (!flutter_controller_->engine() || !flutter_controller_->view()) return false;

  RegisterPlugins(flutter_controller_->engine());

  window_channel_ = std::make_unique<
      flutter::MethodChannel<flutter::EncodableValue>>(
      flutter_controller_->engine()->messenger(),
      "smartis/windows_window",
      &flutter::StandardMethodCodec::GetInstance());

  window_channel_->SetMethodCallHandler(
      [this](const flutter::MethodCall<flutter::EncodableValue>& call,
             std::unique_ptr<flutter::MethodResult<flutter::EncodableValue>> result) {
        const std::string& method = call.method_name();
        HWND hwnd = GetHandle();

        if (method == "initialize") {
          if (!hwnd) {
            result->Error("window_unavailable", "Main window handle is unavailable.");
            return;
          }

          // Native Smartis HUD window configuration: no caption, no resize
          // border, and no native frame around the Flutter scene.
          LONG_PTR style = GetWindowLongPtr(hwnd, GWL_STYLE);
          style &= ~(WS_CAPTION | WS_MINIMIZEBOX | WS_MAXIMIZEBOX |
                     WS_SYSMENU | WS_THICKFRAME);
          style |= WS_POPUP;
          SetWindowLongPtr(hwnd, GWL_STYLE, style);

          LONG_PTR ex_style = GetWindowLongPtr(hwnd, GWL_EXSTYLE);
          ex_style |= WS_EX_APPWINDOW;
          ex_style &= ~WS_EX_DLGMODALFRAME;
          SetWindowLongPtr(hwnd, GWL_EXSTYLE, ex_style);

          HMONITOR monitor = MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST);
          MONITORINFO monitor_info{};
          monitor_info.cbSize = sizeof(monitor_info);
          if (!GetMonitorInfo(monitor, &monitor_info)) {
            result->Error("monitor_unavailable", "Unable to query the current monitor.");
            return;
          }

          // True fullscreen: use the entire physical monitor, not the work area.
          // The Flutter scene itself remains responsible for all HUD layout.
          const RECT& monitor_rect = monitor_info.rcMonitor;
          SetWindowPos(hwnd, HWND_TOP,
                       monitor_rect.left, monitor_rect.top,
                       monitor_rect.right - monitor_rect.left,
                       monitor_rect.bottom - monitor_rect.top,
                       SWP_FRAMECHANGED | SWP_SHOWWINDOW);

          result->Success();
          return;
        }

        if (method == "startDragging") {
          if (!hwnd) {
            result->Error("window_unavailable", "Main window handle is unavailable.");
            return;
          }
          ReleaseCapture();
          SendMessage(hwnd, WM_NCLBUTTONDOWN, HTCAPTION, 0);
          result->Success();
          return;
        }

        if (method == "openLocationSettings") {
          ShellExecuteW(hwnd, L"open", L"ms-settings:privacy-location", nullptr, nullptr, SW_SHOWNORMAL);
          result->Success();
          return;
        }

        if (method == "close") {
          if (hwnd) {
            PostMessage(hwnd, WM_CLOSE, 0, 0);
          }
          result->Success();
          return;
        }

        result->NotImplemented();
      });

  SetChildContent(flutter_controller_->view()->GetNativeWindow());
  flutter_controller_->engine()->SetNextFrameCallback([&]() { this->Show(); });
  flutter_controller_->ForceRedraw();
  return true;
}

void FlutterWindow::OnDestroy() {
  window_channel_ = nullptr;
  flutter_controller_ = nullptr;
  Win32Window::OnDestroy();
}

LRESULT FlutterWindow::MessageHandler(HWND hwnd, UINT const message,
                                      WPARAM const wparam,
                                      LPARAM const lparam) noexcept {
  if (flutter_controller_) {
    std::optional<LRESULT> result = flutter_controller_->HandleTopLevelWindowProc(
        hwnd, message, wparam, lparam);
    if (result) return *result;
  }
  if (message == WM_FONTCHANGE && flutter_controller_) {
    flutter_controller_->engine()->ReloadSystemFonts();
  }
  return Win32Window::MessageHandler(hwnd, message, wparam, lparam);
}
