#include "win32_window.h"

#include <dwmapi.h>
#include <flutter_windows.h>

#include "resource.h"

namespace {
#ifndef DWMWA_USE_IMMERSIVE_DARK_MODE
#define DWMWA_USE_IMMERSIVE_DARK_MODE 20
#endif
constexpr wchar_t kWindowClassName[] = L"FLUTTER_RUNNER_WIN32_WINDOW";
constexpr wchar_t kThemeKey[] = L"Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize";
constexpr wchar_t kThemeValue[] = L"AppsUseLightTheme";
int g_active_window_count = 0;
using EnableNonClientDpiScaling = BOOL __stdcall(HWND hwnd);

int Scale(int value, double factor) { return static_cast<int>(value * factor); }

void EnableFullDpiSupportIfAvailable(HWND hwnd) {
  HMODULE module = LoadLibraryA("User32.dll");
  if (!module) return;
  auto fn = reinterpret_cast<EnableNonClientDpiScaling*>(
      GetProcAddress(module, "EnableNonClientDpiScaling"));
  if (fn) fn(hwnd);
  FreeLibrary(module);
}
}

class WindowClassRegistrar {
 public:
  static WindowClassRegistrar* GetInstance() {
    if (!instance_) instance_ = new WindowClassRegistrar();
    return instance_;
  }
  const wchar_t* GetWindowClass();
  void UnregisterWindowClass();
 private:
  static WindowClassRegistrar* instance_;
  bool class_registered_ = false;
};

WindowClassRegistrar* WindowClassRegistrar::instance_ = nullptr;

const wchar_t* WindowClassRegistrar::GetWindowClass() {
  if (!class_registered_) {
    WNDCLASS window_class{};
    window_class.hCursor = LoadCursor(nullptr, IDC_ARROW);
    window_class.hbrBackground = nullptr;
    window_class.lpszClassName = kWindowClassName;
    window_class.style = CS_HREDRAW | CS_VREDRAW;
    window_class.hInstance = GetModuleHandle(nullptr);
    window_class.hIcon = LoadIcon(window_class.hInstance, MAKEINTRESOURCE(IDI_APP_ICON));
    window_class.lpfnWndProc = Win32Window::WndProc;
    RegisterClass(&window_class);
    class_registered_ = true;
  }
  return kWindowClassName;
}

void WindowClassRegistrar::UnregisterWindowClass() {
  UnregisterClass(kWindowClassName, nullptr);
  class_registered_ = false;
}

Win32Window::Win32Window() { ++g_active_window_count; }
Win32Window::~Win32Window() {
  --g_active_window_count;
  Destroy();
}

bool Win32Window::Create(const std::wstring& title, const Point& origin, const Size& size) {
  Destroy();
  const wchar_t* window_class = WindowClassRegistrar::GetInstance()->GetWindowClass();
  POINT point = {static_cast<LONG>(origin.x), static_cast<LONG>(origin.y)};
  HMONITOR monitor = MonitorFromPoint(point, MONITOR_DEFAULTTONEAREST);
  UINT dpi = FlutterDesktopGetDpiForMonitor(monitor);
  double scale_factor = dpi / 96.0;

  HWND window = CreateWindow(
      window_class, title.c_str(), WS_OVERLAPPEDWINDOW,
      Scale(origin.x, scale_factor), Scale(origin.y, scale_factor),
      Scale(size.width, scale_factor), Scale(size.height, scale_factor),
      nullptr, nullptr, GetModuleHandle(nullptr), this);
  if (!window) return false;
  UpdateTheme(window);
  return OnCreate();
}

bool Win32Window::Show() { return ShowWindow(window_handle_, SW_SHOWNORMAL); }

LRESULT CALLBACK Win32Window::WndProc(HWND window, UINT message, WPARAM wparam,
                                      LPARAM lparam) noexcept {
  if (message == WM_NCCREATE) {
    auto* create_struct = reinterpret_cast<CREATESTRUCT*>(lparam);
    auto* that = static_cast<Win32Window*>(create_struct->lpCreateParams);
    SetWindowLongPtr(window, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(that));
    EnableFullDpiSupportIfAvailable(window);
    that->window_handle_ = window;
  } else if (Win32Window* that = GetThisFromHandle(window)) {
    return that->MessageHandler(window, message, wparam, lparam);
  }
  return DefWindowProc(window, message, wparam, lparam);
}

LRESULT Win32Window::MessageHandler(HWND hwnd, UINT message, WPARAM wparam,
                                    LPARAM lparam) noexcept {
  switch (message) {
    case WM_ERASEBKGND:
      // The Flutter scene and the native transparency layer own every pixel.
      // Do not let Windows paint an opaque theme-colored background.
      return 1;
    case WM_DESTROY:
      window_handle_ = nullptr;
      OnDestroy();
      if (quit_on_close_) PostQuitMessage(0);
      return 0;
    case WM_GETMINMAXINFO: {
      auto* info = reinterpret_cast<MINMAXINFO*>(lparam);
      const UINT dpi = GetDpiForWindow(hwnd);
      const double scale = dpi == 0 ? 1.0 : static_cast<double>(dpi) / 96.0;
      info->ptMinTrackSize.x = static_cast<LONG>(480 * scale);
      info->ptMinTrackSize.y = static_cast<LONG>(620 * scale);
      return 0;
    }
    case WM_DPICHANGED: {
      auto* rect = reinterpret_cast<RECT*>(lparam);
      SetWindowPos(hwnd, nullptr, rect->left, rect->top,
                   rect->right - rect->left, rect->bottom - rect->top,
                   SWP_NOZORDER | SWP_NOACTIVATE);
      return 0;
    }
    case WM_SIZE: {
      RECT rect = GetClientArea();
      if (child_content_) {
        MoveWindow(child_content_, rect.left, rect.top,
                   rect.right - rect.left, rect.bottom - rect.top, TRUE);
      }
      return 0;
    }
    case WM_ACTIVATE:
      if (child_content_) SetFocus(child_content_);
      return 0;
    case WM_DWMCOLORIZATIONCOLORCHANGED:
      UpdateTheme(hwnd);
      return 0;
    default:
      break;
  }
  return DefWindowProc(window_handle_, message, wparam, lparam);
}

void Win32Window::Destroy() {
  OnDestroy();
  if (window_handle_) {
    DestroyWindow(window_handle_);
    window_handle_ = nullptr;
  }
  if (g_active_window_count == 0) {
    WindowClassRegistrar::GetInstance()->UnregisterWindowClass();
  }
}

Win32Window* Win32Window::GetThisFromHandle(HWND window) noexcept {
  return reinterpret_cast<Win32Window*>(GetWindowLongPtr(window, GWLP_USERDATA));
}

void Win32Window::SetChildContent(HWND content) {
  child_content_ = content;
  SetParent(content, window_handle_);
  RECT rect = GetClientArea();
  MoveWindow(content, rect.left, rect.top, rect.right - rect.left,
             rect.bottom - rect.top, true);
  SetFocus(child_content_);
}

RECT Win32Window::GetClientArea() {
  RECT frame{};
  GetClientRect(window_handle_, &frame);
  return frame;
}

HWND Win32Window::GetHandle() { return window_handle_; }
void Win32Window::SetQuitOnClose(bool quit_on_close) { quit_on_close_ = quit_on_close; }
bool Win32Window::OnCreate() { return true; }
void Win32Window::OnDestroy() {}

void Win32Window::UpdateTheme(HWND window) {
  DWORD light_mode = 1;
  DWORD size = sizeof(light_mode);
  if (RegGetValue(HKEY_CURRENT_USER, kThemeKey, kThemeValue, RRF_RT_REG_DWORD,
                  nullptr, &light_mode, &size) == ERROR_SUCCESS) {
    BOOL dark = light_mode == 0;
    DwmSetWindowAttribute(window, DWMWA_USE_IMMERSIVE_DARK_MODE, &dark,
                          sizeof(dark));
  }
}
