using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Linq;
using System.Windows.Forms;
using Microsoft.Win32;
using SimpleScreenshot.Core;

namespace SimpleScreenshot
{
    sealed class HotkeyWindow : NativeWindow, IDisposable
    {
        const int IdBase = 0xB101;
        readonly Dictionary<int, Hotkey> registered = new Dictionary<int, Hotkey>();
        Hotkey[] desired = Array.Empty<Hotkey>();
        internal event Action<int> Pressed;

        internal HotkeyWindow() => CreateHandle(new CreateParams { Parent = new IntPtr(-3) });

        internal string[] Apply(Hotkey[] mapping, bool allowPartial)
        {
            var old = desired;
            Suspend();
            var failed = Register(mapping);
            if (failed.Length > 0 && !allowPartial)
            {
                Suspend();
                Register(old);
                return failed;
            }
            desired = mapping;
            return failed;
        }

        string[] Register(Hotkey[] mapping)
        {
            var failed = new List<string>();
            for (int index = 0; index < mapping.Length; index++)
            {
                var item = mapping[index];
                if (Native.RegisterHotKey(Handle, IdBase + index, (uint)(0x4000 | item.ModifierMask), (uint)item.VirtualKey))
                    registered[index] = item;
                else
                    failed.Add(item.ToString());
            }
            return failed.ToArray();
        }

        internal void Suspend()
        {
            foreach (int index in registered.Keys)
                Native.UnregisterHotKey(Handle, IdBase + index);
            registered.Clear();
        }

        internal string[] Resume()
        {
            Suspend();
            return Register(desired);
        }

        protected override void WndProc(ref Message message)
        {
            if (message.Msg == Native.HotkeyMessage)
            {
                int index = message.WParam.ToInt32() - IdBase;
                if (registered.ContainsKey(index)) Pressed?.Invoke(index);
            }
            base.WndProc(ref message);
        }

        public void Dispose()
        {
            Suspend();
            DestroyHandle();
        }
    }

    static class Startup
    {
        const string Run = @"Software\Microsoft\Windows\CurrentVersion\Run";
        const string Approved = @"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run";
        const string Name = "SimpleScreenshot";
        static string Command => "\"" + Application.ExecutablePath + "\" --autostart";

        internal static bool IsEnabled()
        {
            using (var run = Registry.CurrentUser.OpenSubKey(Run))
            using (var approved = Registry.CurrentUser.OpenSubKey(Approved))
            {
                return string.Equals(run?.GetValue(Name) as string, Command, StringComparison.OrdinalIgnoreCase) &&
                    approved?.GetValue(Name) is byte[] bytes && bytes.Length > 0 && bytes[0] == 2;
            }
        }

        internal static void Set(bool enabled)
        {
            using (var run = Registry.CurrentUser.CreateSubKey(Run))
            using (var approved = Registry.CurrentUser.CreateSubKey(Approved))
            {
                object oldRun = run.GetValue(Name);
                try
                {
                    if (enabled)
                    {
                        run.SetValue(Name, Command, RegistryValueKind.String);
                        var state = new byte[12];
                        state[0] = 2;
                        approved.SetValue(Name, state, RegistryValueKind.Binary);
                    }
                    else
                    {
                        run.DeleteValue(Name, false);
                        approved.DeleteValue(Name, false);
                    }
                }
                catch
                {
                    if (oldRun == null) run.DeleteValue(Name, false);
                    else run.SetValue(Name, oldRun);
                    throw;
                }
            }
        }
    }

    sealed class DesktopSnapshot : IDisposable
    {
        internal Bitmap Bitmap { get; }
        internal Rectangle Bounds { get; }
        internal IReadOnlyList<Native.WindowTarget> Targets { get; }
        int references = 1;

        DesktopSnapshot(Bitmap bitmap, Rectangle bounds, IReadOnlyList<Native.WindowTarget> targets)
        {
            Bitmap = bitmap; Bounds = bounds; Targets = targets;
        }

        internal static DesktopSnapshot Capture()
        {
            var screens = Screen.AllScreens;
            var bounds = screens.Select(s => s.Bounds).Aggregate(Rectangle.Union);
            var image = new Bitmap(bounds.Width, bounds.Height, PixelFormat.Format32bppRgb);
            try
            {
                using (var canvas = Graphics.FromImage(image))
                {
                    canvas.Clear(Color.Black);
                    Native.CopyDesktop(canvas, bounds, screens.Select(screen => screen.Bounds));
                }
                return new DesktopSnapshot(image, bounds, Native.Discover(bounds));
            }
            catch
            {
                image.Dispose();
                throw;
            }
        }

        internal DesktopSnapshot Retain()
        {
            references++;
            return this;
        }

        internal Bitmap Crop(Rectangle selection) => Bitmap.Clone(selection, PixelFormat.Format32bppPArgb);

        public void Dispose()
        {
            if (--references == 0) Bitmap.Dispose();
        }
    }

    static class Output
    {
        static string DragDirectory => Path.Combine(Path.GetTempPath(), "SimpleScreenshot");

        internal static void CleanDragFiles()
        {
            if (!Directory.Exists(DragDirectory)) return;
            foreach (string path in Directory.EnumerateFiles(DragDirectory, "*.png"))
            {
                try
                {
                    if (File.GetLastWriteTimeUtc(path) < DateTime.UtcNow.AddDays(-1))
                        File.Delete(path);
                }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
            }
        }

        internal static string Drag(Bitmap image) => Save(image, DragDirectory);

        internal static string Save(Bitmap image, string directory)
        {
            Directory.CreateDirectory(directory);
            string path = OutputNames.UniquePng(directory, DateTime.Now, File.Exists);
            string temporary = Path.Combine(directory, "." + Path.GetFileName(path) + ".tmp");
            try
            {
                image.Save(temporary, ImageFormat.Png);
                File.Move(temporary, path);
                return path;
            }
            finally { File.Delete(temporary); }
        }
    }
}
