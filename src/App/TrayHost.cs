using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using System.Windows.Forms;
using SimpleScreenshot.Core;

namespace SimpleScreenshot
{
    sealed class TrayHost : ApplicationContext
    {
        static readonly string Title = "简易截图工具";
        readonly Control dispatch = new Control();
        readonly SettingsStore store = new SettingsStore(Program.DataDirectory, AppDomain.CurrentDomain.BaseDirectory);
        readonly NotifyIcon tray = new NotifyIcon();
        readonly ContextMenuStrip menu = new ContextMenuStrip { Renderer = new ToolStripRenderer(), Font = Theme.UiFont };
        readonly HotkeyWindow hotkeys = new HotkeyWindow();
        readonly List<PinForm> pins = new List<PinForm>();
        readonly List<EditorForm> editors = new List<EditorForm>();
        readonly Timer click = new Timer { Interval = SystemInformation.DoubleClickTime };
        readonly OcrClient ocr = new OcrClient();
        readonly ToolStripMenuItem unlock, close, last, autostart;
        readonly Icon icon;
        Settings settings;
        SettingsForm settingsForm;
        SelectionForm selectionForm;
        Rectangle lastSelection;
        Bitmap lastImage;
        string previousSave, saveAsDirectory;
        bool pending, exiting;

        internal TrayHost(bool quiet)
        {
            _ = dispatch.Handle;
            settings = store.Load();
            try { Output.CleanDragFiles(); } catch (Exception error) { Log.Write(error); }

            Item("截图并复制", () => Capture(CaptureAction.Copy));
            Item("截图并保存", () => Capture(CaptureAction.Save));
            Item("截图并钉住", () => Capture(CaptureAction.Pin));
            Item("全屏截图", () => Capture(CaptureAction.Copy, true));
            menu.Items.Add(new ToolStripSeparator());
            Item("贴图剪贴板图片", ClipboardPin);
            unlock = Item("恢复贴图可点击", () => ForPins(pin => pin.SetClickThrough(false)));
            last = Item("保存最近一张截图", () => { if (lastImage != null) Save(lastImage, false, false); });
            close = Item("关闭所有贴图", () => ForPins(pin => pin.Close()));
            menu.Items.Add(new ToolStripSeparator());
            Item("打开截图文件夹", OpenSaveDirectory);
            Item("设置…", ShowSettings);
            autostart = Item("开机启动", ToggleStartup);
            menu.Items.Add(new ToolStripSeparator());
            Item("关于", About);
            Item("退出", ExitThread);

            var warnings = new List<string>();
            if (store.LastWarning != null) warnings.Add(store.LastWarning);
            string[] failed = hotkeys.Apply(settings.ParseHotkeys(), true);
            if (failed.Length > 0) warnings.Add("快捷键已被占用：" + string.Join("、", failed));
            try
            {
                if (settings.StartWithWindows) Startup.Set(true);
                autostart.Checked = Startup.IsEnabled();
            }
            catch (Exception error) { Log.Write(error); warnings.Add("无法更新开机启动：" + error.Message); }
            hotkeys.Pressed += index => Capture((CaptureAction)index);
            icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            tray.Icon = icon ?? SystemIcons.Application;
            tray.ContextMenuStrip = menu;
            tray.Visible = true;
            tray.MouseClick += (_, e) => { if (e.Button == MouseButtons.Left) { click.Stop(); click.Start(); } };
            tray.MouseDoubleClick += (_, e) => { if (e.Button == MouseButtons.Left) { click.Stop(); ShowSettings(); } };
            tray.BalloonTipClicked += (_, __) => OpenLastSaved();
            click.Tick += (_, __) => { click.Stop(); Capture(CaptureAction.Copy); };
            menu.Opening += (_, __) => RefreshMenu();
            SyncTooltip();
            Post(() =>
            {
                if (warnings.Count > 0) Notice("已启动，但有设置需要处理", Summary() + "\n" + string.Join("\n", warnings), true);
                else if (!quiet) Notice("截图工具已启动", Summary());
            });
        }

        ToolStripMenuItem Item(string title, Action action)
        {
            var item = new ToolStripMenuItem(title);
            item.Click += (_, __) => Post(action);
            menu.Items.Add(item);
            return item;
        }

        void Post(Action action)
        {
            if (!exiting && !dispatch.IsDisposed)
            {
                try
                {
                    dispatch.BeginInvoke((Action)(() =>
                    {
                        if (exiting) return;
                        try { action(); }
                        catch (Exception error) { Log.Write(error); Notice("操作失败", error.Message, true); }
                    }));
                }
                catch (InvalidOperationException) when (exiting || dispatch.IsDisposed) { }
            }
        }

        void RefreshMenu()
        {
            close.Enabled = pins.Count != 0;
            unlock.Enabled = pins.Any(pin => pin.ClickThrough);
            last.Enabled = lastImage != null;
            try
            {
                bool enabled = Startup.IsEnabled();
                autostart.Checked = enabled;
                if (settings.StartWithWindows != enabled)
                {
                    settings.StartWithWindows = enabled;
                    store.Save(settings);
                }
            }
            catch (Exception error) { Log.Write(error); }
        }

        string Summary() => $"{settings.CopyHotkey} 复制 · {settings.SaveHotkey} 保存 · {settings.PinHotkey} 钉住";
        void SyncTooltip()
        {
            string tip = Title + "\n" + Summary() + "\n单击截图 · 双击设置";
            tray.Text = tip.Length > 63 ? tip.Substring(0, 63) : tip;
        }

        void Notice(string title, string text, bool warning = false)
        {
            if (!exiting)
                tray.ShowBalloonTip(4500, title, text, warning ? ToolTipIcon.Warning : ToolTipIcon.Info);
        }

        internal void UsedAgain() => Post(() => Notice("截图工具正在运行", Summary()));

        void ShowSettings()
        {
            if (pending || selectionForm != null) return;
            if (settingsForm == null)
            {
                settingsForm = new SettingsForm(settings, Settings.Defaults(store.ProgramDirectory), value => ApplySettings(value));
                settingsForm.Recording += active =>
                {
                    if (active) hotkeys.Suspend();
                    else
                    {
                        string[] failed = hotkeys.Resume();
                        if (failed.Length > 0) Notice("快捷键未能恢复", string.Join("、", failed) + " 已被其他程序占用。", true);
                    }
                };
                settingsForm.FormClosed += (_, __) => settingsForm = null;
            }
            settingsForm.Show();
            settingsForm.Activate();
        }

        string ApplySettings(Settings candidate)
        {
            var failed = hotkeys.Apply(candidate.ParseHotkeys(), false);
            if (failed.Length > 0) return "快捷键已被占用：" + string.Join("、", failed);
            bool originalStartup = settings.StartWithWindows;
            try
            {
                Startup.Set(candidate.StartWithWindows);
                store.Save(candidate);
            }
            catch (Exception error)
            {
                Log.Write(error);
                hotkeys.Apply(settings.ParseHotkeys(), true);
                try { Startup.Set(originalStartup); } catch (Exception fallbackError) { Log.Write(fallbackError); }
                return error.Message;
            }
            settings = candidate;
            autostart.Checked = candidate.StartWithWindows;
            SyncTooltip();
            Notice("设置已保存", "新的设置已经生效。");
            return null;
        }

        void ToggleStartup()
        {
            var updated = new Settings
            {
                CopyHotkey = settings.CopyHotkey, SaveHotkey = settings.SaveHotkey, PinHotkey = settings.PinHotkey,
                SaveDirectory = settings.SaveDirectory, HidePinsOnCapture = settings.HidePinsOnCapture,
                StartWithWindows = !autostart.Checked
            };
            string failed = ApplySettings(updated);
            if (failed != null) Notice("开机启动设置失败", failed, true);
        }

        void Capture(CaptureAction action, bool fullscreen = false)
        {
            if (pending || selectionForm != null) return;
            pending = true;
            var previousSettings = settingsForm?.Visible == true ? settingsForm : null;
            var hiddenPins = settings.HidePinsOnCapture ? pins.Where(pin => pin.Visible).ToArray() : Array.Empty<PinForm>();
            previousSettings?.Hide();
            foreach (var pin in hiddenPins) pin.Hide();
            void Restore()
            {
                foreach (var pin in hiddenPins)
                    if (!exiting && !pin.IsDisposed) pin.Show();
                if (!exiting && previousSettings != null && !previousSettings.IsDisposed) previousSettings.Show();
            }
            try
            {
                if (hiddenPins.Length > 0 || previousSettings != null) Native.DwmFlush();
                var snapshot = DesktopSnapshot.Capture();
                OpenOverlay(snapshot, action, Rectangle.Empty, false, fullscreen, Restore);
            }
            catch (Exception error)
            {
                Restore();
                Log.Write(error);
                Notice("截图失败", error.Message, true);
            }
            finally { pending = false; }
        }

        void OpenOverlay(DesktopSnapshot snapshot, CaptureAction action, Rectangle initial,
            bool fineTune, bool fullscreen = false, Action restored = null)
        {
            SelectionForm window = null;
            try
            {
                window = new SelectionForm(snapshot, action, initial, fineTune, () => lastSelection, crop =>
                {
                    var position = new Point(snapshot.Bounds.X + crop.X, snapshot.Bounds.Y + crop.Y);
                    var image = snapshot.Crop(crop);
                    lastSelection = new Rectangle(position, crop.Size);
                    if (action != CaptureAction.Pin) snapshot.Retain();
                    window.Close();
                    if (action == CaptureAction.Pin)
                    {
                        UpdateLast(image);
                        OpenPin(image, position, false);
                    }
                    else OpenEditor(snapshot, image, action, position, crop);
                });
                window.FormClosed += (_, __) =>
                {
                    selectionForm = null;
                    restored?.Invoke();
                };
                selectionForm = window;
                window.Show();
                window.Activate();
                if (fullscreen) window.FullScreen();
            }
            catch
            {
                if (window == null) snapshot.Dispose();
                else if (!window.IsDisposed) window.Dispose();
                if (selectionForm == window) selectionForm = null;
                throw;
            }
        }

        void OpenEditor(DesktopSnapshot snapshot, Bitmap image, CaptureAction action, Point point, Rectangle crop)
        {
            EditorForm editor = null;
            try
            {
                editor = new EditorForm(image, action, point, Complete, precise =>
                {
                    if (selectionForm != null || pending) return;
                    snapshot.Retain();
                    editor.Close();
                    OpenOverlay(snapshot, action, precise ? crop : Rectangle.Empty, precise);
                }, ocr.Recognize);
                editors.Add(editor);
                editor.FormClosed += (_, __) => { editors.Remove(editor); snapshot.Dispose(); };
                editor.Show();
                editor.Activate();
            }
            catch
            {
                if (editor == null) image.Dispose();
                else if (!editor.IsDisposed)
                {
                    editors.Remove(editor);
                    editor.Dispose();
                }
                snapshot.Dispose();
                throw;
            }
        }

        bool Complete(Bitmap output, CaptureAction action)
        {
            UpdateLast(output);
            if (action == CaptureAction.Save) return Save(output, false, false) == true;
            if (action == CaptureAction.SaveAs) return Save(output, true, true) != false;
            try { Clipboard.SetImage(output); return true; }
            catch (Exception error) { Log.Write(error); Notice("复制失败", error.Message, true); return false; }
        }

        void UpdateLast(Bitmap source)
        {
            var copy = new Bitmap(source);
            lastImage?.Dispose();
            lastImage = copy;
        }

        void OpenPin(Bitmap source, Point where, bool fit)
        {
            PinForm form = null;
            try
            {
                form = new PinForm(source, where, fit, (image, asFile) => Save(image, asFile, false),
                    () => ForPins(pin => pin.Close()), ocr.Recognize);
                pins.Add(form);
                form.FormClosed += (_, __) => pins.Remove(form);
                form.Show();
                form.ShowHint();
            }
            catch
            {
                if (form == null) source.Dispose();
                else { pins.Remove(form); form.Dispose(); }
                throw;
            }
        }

        void ClipboardPin()
        {
            using (var data = Clipboard.GetImage())
            {
                if (data == null) { Notice("剪贴板里没有图片", "复制一张图片后再试。", true); return; }
                OpenPin(new Bitmap(data), Cursor.Position, true);
            }
        }

        bool? Save(Bitmap image, bool saveAs, bool clipboardOnCancel)
        {
            try
            {
                string path;
                if (saveAs)
                {
                    string directory = saveAsDirectory ?? settings.SaveDirectory;
                    using (var dialog = new SaveFileDialog
                    {
                        Title = "另存截图", Filter = "PNG 图片 (*.png)|*.png", DefaultExt = "png", AddExtension = true,
                        FileName = Path.GetFileName(OutputNames.UniquePng(directory, DateTime.Now, File.Exists)),
                        InitialDirectory = directory
                    })
                    {
                        pending = true;
                        var visible = pins.Where(pin => pin.Visible).ToArray();
                        foreach (var pin in visible) pin.Hide();
                        DialogResult result;
                        try { result = dialog.ShowDialog(); }
                        finally
                        {
                            pending = false;
                            foreach (var pin in visible) if (!pin.IsDisposed) pin.Show();
                        }
                        if (result != DialogResult.OK)
                        {
                            if (clipboardOnCancel) { Clipboard.SetImage(image); Notice("已取消另存", "截图已复制到剪贴板。"); }
                            return null;
                        }
                        path = OutputNames.WithPngExtension(dialog.FileName);
                    }
                    image.Save(path, ImageFormat.Png);
                    saveAsDirectory = Path.GetDirectoryName(path);
                }
                else path = Output.Save(image, settings.SaveDirectory);
                previousSave = path;
                Notice("截图已保存", path + "\n点击通知可打开所在文件夹。");
                return true;
            }
            catch (Exception error)
            {
                Log.Write(error);
                string message = "无法写入截图：" + error.Message;
                try { Clipboard.SetImage(image); message += "\n截图已复制到剪贴板。"; }
                catch (Exception clipboardError) { Log.Write(clipboardError); }
                Notice("保存失败", message, true);
                return false;
            }
        }

        void ForPins(Action<PinForm> action)
        {
            foreach (var pin in pins.ToArray()) if (!pin.IsDisposed) action(pin);
        }

        void OpenSaveDirectory()
        {
            Directory.CreateDirectory(settings.SaveDirectory);
            Process.Start("explorer.exe", "\"" + settings.SaveDirectory + "\"");
        }

        void OpenLastSaved()
        {
            if (previousSave != null && File.Exists(previousSave))
                Process.Start("explorer.exe", "/select,\"" + previousSave + "\"");
        }

        void About() => MessageBox.Show($"{Title}\n版本：{typeof(TrayHost).Assembly.GetName().Version.ToString(3)}" +
            "\n项目地址：https://github.com/ciaooo55/simple-screenshot\n作者：ciaooo55", "关于简易截图工具");

        protected override void ExitThreadCore()
        {
            exiting = true;
            selectionForm?.Close();
            ForPins(pin => pin.Close());
            foreach (var editor in editors.ToArray()) editor.Close();
            settingsForm?.Close();
            base.ExitThreadCore();
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                exiting = true;
                lastImage?.Dispose();
                click.Dispose();
                hotkeys.Dispose();
                ocr.Dispose();
                tray.Visible = false;
                tray.Dispose();
                menu.Dispose();
                icon?.Dispose();
                dispatch.Dispose();
            }
            base.Dispose(disposing);
        }
    }
}
