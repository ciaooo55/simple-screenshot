using System;
using System.Drawing;
using System.IO;
using System.Windows.Forms;
using SimpleScreenshot.Core;

namespace SimpleScreenshot
{
    sealed class SettingsForm : Form
    {
        readonly HotkeyBox[] keys;
        readonly TextBox directory;
        readonly CheckBox startup, hidePins;
        readonly Func<Settings, string> save;
        readonly Settings defaults;
        internal event Action<bool> Recording;

        internal SettingsForm(Settings value, Settings defaults, Func<Settings, string> save)
        {
            this.save = save;
            this.defaults = defaults;
            Text = "简易截图工具 · 设置";
            StartPosition = FormStartPosition.CenterScreen;
            Font = Theme.UiFont;
            BackColor = Theme.Background;
            ForeColor = Theme.Ink;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            AutoScaleMode = AutoScaleMode.Font;
            MaximizeBox = MinimizeBox = false;
            ClientSize = new Size(559, 468);
            Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);

            var root = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 5, Padding = new Padding(16),
                BackColor = Theme.Background };
            root.RowStyles.Add(new RowStyle(SizeType.Absolute, 63));
            root.RowStyles.Add(new RowStyle(SizeType.Absolute, 153));
            root.RowStyles.Add(new RowStyle(SizeType.Absolute, 125));
            root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            root.RowStyles.Add(new RowStyle(SizeType.Absolute, 36));

            var head = new Panel { Dock = DockStyle.Fill };
            head.Controls.Add(new Label { Text = "截图工具设置", Font = Theme.Heading, ForeColor = Theme.Ink,
                AutoSize = true, Location = new Point(4, 4) });
            head.Controls.Add(new Label { Text = "设置截图快捷键、默认存放位置和贴图行为。", ForeColor = Theme.Muted,
                AutoSize = true, Location = new Point(5, 31) });
            root.Controls.Add(head, 0, 0);

            var keyboard = Section("全局快捷键", "点击输入框后直接按键，录制期间会暂停全局注册。");
            keys = new HotkeyBox[3];
            string[] names = { "截图并复制", "截图并保存", "截图并钉住" };
            for (int i = 0; i < keys.Length; i++)
            {
                keyboard.Controls.Add(new Label { Text = names[i], AutoSize = true, Location = new Point(18, 58 + 26 * i) });
                keys[i] = new HotkeyBox { Location = new Point(116, 54 + 26 * i), Width = 219, AccessibleName = names[i] };
                keys[i].GotFocus += (_, __) => Recording?.Invoke(true);
                keys[i].LostFocus += (_, __) => Recording?.Invoke(false);
                keyboard.Controls.Add(keys[i]);
            }
            root.Controls.Add(keyboard, 0, 1);

            var files = Section("保存与系统", "默认保存 PNG 到程序目录下的 tp 文件夹。");
            directory = new TextBox { Location = new Point(17, 54), Size = new Size(392, 24), AccessibleName = "保存目录" };
            var browse = new Button { Text = "浏览…", Location = new Point(417, 52), Size = new Size(76, 25) };
            browse.Click += (_, __) =>
            {
                using (var dialog = new FolderBrowserDialog { Description = "选择截图保存目录", SelectedPath = directory.Text })
                    if (dialog.ShowDialog(this) == DialogResult.OK) directory.Text = dialog.SelectedPath;
            };
            startup = new CheckBox { Text = "登录 Windows 后自动启动", AutoSize = true, Location = new Point(17, 84) };
            files.Controls.AddRange(new Control[] { directory, browse, startup });
            root.Controls.Add(files, 0, 2);
            hidePins = new CheckBox { Text = "截图时隐藏已有贴图（关闭时会将其一起截入）",
                AutoSize = true, Anchor = AnchorStyles.Left, Margin = new Padding(10, 0, 0, 0) };
            root.Controls.Add(hidePins, 0, 3);

            var buttons = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.RightToLeft,
                WrapContents = false };
            var ok = new Button { Text = "保存", Size = new Size(86, 30), FlatStyle = FlatStyle.Flat,
                BackColor = Theme.Accent, ForeColor = Color.White };
            ok.FlatAppearance.BorderSize = 0;
            ok.Click += (_, __) => Save();
            var cancel = new Button { Text = "取消", Size = ok.Size, DialogResult = DialogResult.Cancel };
            cancel.Click += (_, __) => Close();
            var restore = new Button { Text = "恢复默认", Size = ok.Size };
            restore.Click += (_, __) => Populate(this.defaults);
            buttons.Controls.AddRange(new Control[] { ok, cancel, restore });
            root.Controls.Add(buttons, 0, 4);
            Controls.Add(root);
            AcceptButton = ok;
            CancelButton = cancel;
            Populate(value);
            ActiveControl = ok;
        }

        Panel Section(string title, string description)
        {
            var group = new Panel { Dock = DockStyle.Fill, BackColor = Theme.Paper, Margin = new Padding(3, 0, 3, 8) };
            group.Controls.Add(new Label { Text = title, ForeColor = Theme.Ink, Font = Theme.Heading, AutoSize = true,
                Location = new Point(14, 7) });
            group.Controls.Add(new Label { Text = description, ForeColor = Theme.Muted, AutoSize = true,
                Location = new Point(16, 32) });
            return group;
        }

        void Populate(Settings settings)
        {
            keys[0].Text = settings.CopyHotkey;
            keys[1].Text = settings.SaveHotkey;
            keys[2].Text = settings.PinHotkey;
            directory.Text = settings.SaveDirectory;
            startup.Checked = settings.StartWithWindows;
            hidePins.Checked = settings.HidePinsOnCapture;
        }

        void Save()
        {
            try
            {
                string path = directory.Text.Trim();
                if (path.Length == 0) throw new ArgumentException("保存目录不能为空。");
                path = Path.GetFullPath(path);
                Directory.CreateDirectory(path);
                string test = Path.Combine(path, ".simple_screenshot_" + Guid.NewGuid().ToString("N") + ".tmp");
                using (new FileStream(test, FileMode.CreateNew, FileAccess.Write, FileShare.None, 1, FileOptions.DeleteOnClose)) { }
                var updated = new Settings
                {
                    CopyHotkey = keys[0].Text, SaveHotkey = keys[1].Text, PinHotkey = keys[2].Text,
                    SaveDirectory = path, StartWithWindows = startup.Checked, HidePinsOnCapture = hidePins.Checked
                };
                updated.ParseHotkeys();
                string error = save(updated);
                if (error != null) throw new InvalidOperationException(error);
                Close();
            }
            catch (Exception error)
            {
                MessageBox.Show(this, error.Message, "设置保存失败", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
        }
    }

    sealed class HotkeyBox : TextBox
    {
        bool dismiss;
        internal HotkeyBox() { ReadOnly = true; BackColor = Theme.Paper; ShortcutsEnabled = false; }

        protected override bool ProcessCmdKey(ref Message message, Keys data)
        {
            if (data == Keys.Tab || data == (Keys.Shift | Keys.Tab)) return base.ProcessCmdKey(ref message, data);
            var key = data & Keys.KeyCode;
            if (key == Keys.ControlKey || key == Keys.ShiftKey || key == Keys.Menu || key == Keys.LWin || key == Keys.RWin)
                return true;
            int mask = ((data & Keys.Alt) == 0 ? 0 : 1) | ((data & Keys.Control) == 0 ? 0 : 2) |
                ((data & Keys.Shift) == 0 ? 0 : 4) | (Native.WinDown ? 8 : 0);
            try
            {
                Text = new Hotkey(mask, (int)key).ToString();
                AccessibleDescription = "当前快捷键：" + Text;
                dismiss = false;
            }
            catch (ArgumentException error)
            {
                if (!dismiss)
                    MessageBox.Show(this, error.Message, "无效的快捷键", MessageBoxButtons.OK, MessageBoxIcon.Information);
                dismiss = true;
            }
            return true;
        }
    }
}
