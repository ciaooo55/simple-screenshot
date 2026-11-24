using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Linq;
using System.Windows.Forms;
using SimpleScreenshot.Core;

namespace SimpleScreenshot
{
    enum CaptureAction { Copy, Save, Pin, SaveAs }

    sealed class SelectionForm : Form
    {
        const int HandleRadius = 5;
        const int MinimumSelectionSize = 2;
        readonly DesktopSnapshot snapshot;
        readonly Action<Rectangle> accept;
        readonly Func<Rectangle> lastSelection;
        readonly Ribbon ribbon = new Ribbon();
        Rectangle selection, original;
        Point cursor, origin;
        Native.WindowTarget hoverWindow, pressedWindow;
        int handleX, handleY;
        bool dragging, areaDragStarted, moving, fineTune, help, cursorKnown;
        string notice;
        readonly Timer noticeTimer = new Timer { Interval = 1000 };

        internal SelectionForm(DesktopSnapshot snapshot, CaptureAction action, Rectangle initial, bool precise,
            Func<Rectangle> lastSelection, Action<Rectangle> accept)
        {
            this.snapshot = snapshot;
            this.accept = accept;
            this.lastSelection = lastSelection;
            selection = initial;
            fineTune = precise;
            StartPosition = FormStartPosition.Manual;
            FormBorderStyle = FormBorderStyle.None;
            AutoScaleMode = AutoScaleMode.None;
            ShowInTaskbar = false;
            TopMost = true;
            DoubleBuffered = true;
            KeyPreview = true;
            Cursor = Cursors.Cross;
            Bounds = snapshot.Bounds;
            ribbon.Add("重新框选", "crop", "清空选区并重新框选", Reset);
            ribbon.Add("快捷键", "more", "快捷键帮助（F1）", () => { help = !help; Invalidate(); });
            ribbon.Add(action == CaptureAction.Pin ? "确定钉住" : "开始标注", action == CaptureAction.Pin ? "pin" : "pen",
                "确认选区（Enter 或双击）", Accept).Selected = true;
            Controls.Add(ribbon);
            LayoutRibbon();
            noticeTimer.Tick += (_, __) => { notice = null; noticeTimer.Stop(); Invalidate(); };
        }

        Rectangle ImageBounds => new Rectangle(Point.Empty, snapshot.Bounds.Size);
        bool HasSelection => selection.Width >= MinimumSelectionSize && selection.Height >= MinimumSelectionSize;
        static bool ShiftDown => (ModifierKeys & Keys.Shift) != 0;

        internal void FullScreen()
        {
            selection = ImageBounds;
            if (fineTune) { LayoutRibbon(); Invalidate(); }
            else Accept();
        }

        void Accept()
        {
            if (HasSelection) accept(selection);
        }

        void Reset()
        {
            selection = Rectangle.Empty;
            dragging = moving = false;
            Capture = false;
            LayoutRibbon();
            Invalidate();
        }

        void LayoutRibbon()
        {
            ribbon.Visible = fineTune && HasSelection && !dragging;
            if (!ribbon.Visible) return;
            int x = Geometry.Clamp(selection.Right - ribbon.Width, 4, Math.Max(4, ClientSize.Width - ribbon.Width - 4));
            int y = selection.Bottom + 9;
            if (y + ribbon.Height > ClientSize.Height - 4)
                y = Math.Max(4, selection.Top - ribbon.Height - 9);
            ribbon.Location = new Point(x, y);
        }

        void SetPointer(Point point)
        {
            cursor = new Point(Geometry.Clamp(point.X, 0, ImageBounds.Width - 1),
                Geometry.Clamp(point.Y, 0, ImageBounds.Height - 1));
            cursorKnown = true;
            hoverWindow = !fineTune || !HasSelection ? snapshot.Targets.FirstOrDefault(target => target.Bounds.Contains(cursor)) : null;
        }

        protected override void OnShown(EventArgs e)
        {
            base.OnShown(e);
            Activate();
            SetPointer(PointToClient(MousePosition));
            LayoutRibbon();
            Invalidate();
        }

        protected override void OnMouseDown(MouseEventArgs e)
        {
            if (e.Button == MouseButtons.Right)
            {
                if (help) help = false;
                else if (dragging) CancelDrag();
                else if (HasSelection) Reset();
                else Close();
                Invalidate();
                return;
            }
            if (e.Button != MouseButtons.Left) return;
            if (help) { help = false; Invalidate(); return; }
            SetPointer(e.Location);
            origin = cursor;
            original = selection;
            handleX = handleY = 0;
            areaDragStarted = false;
            moving = false;
            pressedWindow = hoverWindow;
            if (fineTune && HasSelection)
            {
                (handleX, handleY) = HandleAt(cursor);
                moving = handleX == 0 && handleY == 0 && selection.Contains(cursor);
            }
            dragging = true;
            Capture = true;
            LayoutRibbon();
        }

        protected override void OnMouseMove(MouseEventArgs e)
        {
            SetPointer(e.Location);
            if (dragging) Track();
            else if (fineTune && HasSelection)
            {
                var (x, y) = HandleAt(cursor);
                Cursor = x == 0 && y == 0 ? (selection.Contains(cursor) ? Cursors.SizeAll : Cursors.Cross) :
                    x == 0 ? Cursors.SizeNS : y == 0 ? Cursors.SizeWE : x == y ? Cursors.SizeNWSE : Cursors.SizeNESW;
            }
            else Cursor = Cursors.Cross;
            Invalidate();
        }

        void Track()
        {
            int dx = cursor.X - origin.X, dy = cursor.Y - origin.Y;
            if (moving)
            {
                selection = new Rectangle(Geometry.Clamp(original.X + dx, 0, ImageBounds.Width - original.Width),
                    Geometry.Clamp(original.Y + dy, 0, ImageBounds.Height - original.Height), original.Width, original.Height);
            }
            else if (handleX != 0 || handleY != 0)
            {
                int left = original.Left, right = original.Right, top = original.Top, bottom = original.Bottom;
                if (handleX < 0) left = Geometry.Clamp(left + dx, 0, right - MinimumSelectionSize);
                if (handleX > 0) right = Geometry.Clamp(right + dx, left + MinimumSelectionSize, ImageBounds.Right);
                if (handleY < 0) top = Geometry.Clamp(top + dy, 0, bottom - MinimumSelectionSize);
                if (handleY > 0) bottom = Geometry.Clamp(bottom + dy, top + MinimumSelectionSize, ImageBounds.Bottom);
                selection = Rectangle.FromLTRB(left, top, right, bottom);
            }
            else
                selection = Geometry.SelectionFromDrag(origin, cursor, ImageBounds.Size, ShiftDown,
                    SystemInformation.DragSize, ref areaDragStarted);
        }

        protected override void OnMouseUp(MouseEventArgs e)
        {
            if (e.Button != MouseButtons.Left || !dragging) return;
            SetPointer(e.Location);
            Track();
            bool transformed = moving || handleX != 0 || handleY != 0;
            dragging = moving = false;
            Capture = false;
            if (!transformed && !HasSelection)
                selection = Geometry.AreaSelectionFallback(original, pressedWindow?.Bounds, areaDragStarted);
            LayoutRibbon();
            Invalidate();
            if (!fineTune && HasSelection) Accept();
        }

        protected override void OnMouseDoubleClick(MouseEventArgs e)
        {
            if (e.Button == MouseButtons.Left && fineTune && selection.Contains(e.Location))
            {
                CancelDrag();
                Accept();
            }
        }

        (int, int) HandleAt(Point p)
        {
            foreach (int x in new[] { -1, 0, 1 })
                foreach (int y in new[] { -1, 0, 1 })
                {
                    if (x == 0 && y == 0) continue;
                    Point point = HandlePoint(x, y);
                    if (Math.Abs(p.X - point.X) <= HandleRadius + 2 && Math.Abs(p.Y - point.Y) <= HandleRadius + 2)
                        return (x, y);
                }
            return (0, 0);
        }

        Point HandlePoint(int x, int y) => new Point(
            x < 0 ? selection.Left : x > 0 ? selection.Right - 1 : selection.Left + selection.Width / 2,
            y < 0 ? selection.Top : y > 0 ? selection.Bottom - 1 : selection.Top + selection.Height / 2);

        void CancelDrag()
        {
            if (!dragging) return;
            selection = original;
            dragging = moving = false;
            Capture = false;
            LayoutRibbon();
            Invalidate();
        }

        protected override bool ProcessCmdKey(ref Message message, Keys data)
        {
            var key = data & Keys.KeyCode;
            if (key == Keys.F1 || data == Keys.H) { help = !help; Invalidate(); return true; }
            if (help) { help = false; Invalidate(); return true; }
            if (key == Keys.Escape)
            {
                if (dragging) CancelDrag();
                else Close();
                return true;
            }
            if (data == Keys.Tab)
            {
                fineTune = true;
                LayoutRibbon();
                Invalidate();
                return true;
            }
            if (data == Keys.Enter) { Accept(); return true; }
            if (data == (Keys.Control | Keys.A)) { FullScreen(); return true; }
            if (data == Keys.R && !dragging)
            {
                var previous = Geometry.RestoreSelection(lastSelection(), snapshot.Bounds);
                if (previous.Width >= MinimumSelectionSize && previous.Height >= MinimumSelectionSize)
                {
                    selection = previous;
                    if (fineTune) { LayoutRibbon(); Invalidate(); }
                    else Accept();
                }
                return true;
            }
            if (data == Keys.C && cursorKnown)
            {
                Color color = snapshot.Bitmap.GetPixel(cursor.X, cursor.Y);
                string hex = $"#{color.R:X2}{color.G:X2}{color.B:X2}";
                try { Clipboard.SetText(hex); notice = "已复制 " + hex; }
                catch (Exception error) { Log.Write(error); notice = "无法访问剪贴板"; }
                noticeTimer.Stop();
                noticeTimer.Start();
                Invalidate();
                return true;
            }
            if (HasSelection && fineTune && !dragging && key >= Keys.Left && key <= Keys.Down)
            {
                int step = (data & Keys.Shift) != 0 ? 10 : 1;
                int x = key == Keys.Left ? -step : key == Keys.Right ? step : 0;
                int y = key == Keys.Up ? -step : key == Keys.Down ? step : 0;
                if ((data & Keys.Control) == 0)
                    selection.Location = new Point(Geometry.Clamp(selection.X + x, 0, ImageBounds.Width - selection.Width),
                        Geometry.Clamp(selection.Y + y, 0, ImageBounds.Height - selection.Height));
                else selection.Size = new Size(Geometry.Clamp(selection.Width + x, MinimumSelectionSize, ImageBounds.Right - selection.X),
                    Geometry.Clamp(selection.Height + y, MinimumSelectionSize, ImageBounds.Bottom - selection.Y));
                LayoutRibbon();
                Invalidate();
                return true;
            }
            return base.ProcessCmdKey(ref message, data);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            var g = e.Graphics;
            Rectangle invalid = Rectangle.Intersect(e.ClipRectangle, ImageBounds);
            if (invalid.Width > 0 && invalid.Height > 0)
                g.DrawImage(snapshot.Bitmap, invalid, invalid, GraphicsUnit.Pixel);
            Rectangle focus = HasSelection ? selection : hoverWindow?.Bounds ?? Rectangle.Empty;
            using (var dim = new Region(ClientRectangle))
            using (var shade = new SolidBrush(Color.FromArgb(132, 12, 19, 33)))
            {
                if (!focus.IsEmpty) dim.Exclude(focus);
                g.FillRegion(shade, dim);
            }
            if (!focus.IsEmpty)
            {
                using (var pen = new Pen(Color.FromArgb(84, 183, 255), 2))
                    g.DrawRectangle(pen, focus.X, focus.Y, Math.Max(0, focus.Width - 1), Math.Max(0, focus.Height - 1));
                if (fineTune && HasSelection && !dragging)
                {
                    for (int x = -1; x <= 1; x++)
                        for (int y = -1; y <= 1; y++)
                            if (x != 0 || y != 0)
                            {
                                var point = HandlePoint(x, y);
                                g.FillRectangle(Brushes.White, point.X - 3, point.Y - 3, 7, 7);
                                using (var outline = new Pen(Theme.Accent))
                                    g.DrawRectangle(outline, point.X - 3, point.Y - 3, 7, 7);
                            }
                }
                string size = $"{focus.Width} × {focus.Height} 像素";
                string text = !HasSelection && hoverWindow != null ? hoverWindow.Title + "  ·  " + size : size;
                int width = Math.Min(450, TextRenderer.MeasureText(text, Theme.UiFont).Width + 18);
                var label = new Rectangle(Geometry.Clamp(focus.X, 3, Math.Max(3, Width - width - 3)),
                    Math.Max(3, focus.Top - 30), width, 25);
                Theme.Card(g, label, Theme.Dark, 6);
                label.Inflate(-7, 0);
                Theme.Text(g, text, Theme.UiFont, label, Color.White);
            }
            if (cursorKnown && (!HasSelection || dragging && !moving)) DrawMagnifier(g);
            if (help) DrawHelp(g);
        }

        void DrawMagnifier(Graphics g)
        {
            var screen = Screen.FromPoint(new Point(snapshot.Bounds.X + cursor.X, snapshot.Bounds.Y + cursor.Y)).Bounds;
            screen.Offset(-snapshot.Bounds.X, -snapshot.Bounds.Y);
            int x = cursor.X + 23, y = cursor.Y + 23;
            const int width = 166, height = 117;
            if (x + width > screen.Right) x = cursor.X - width - 20;
            if (y + height > screen.Bottom) y = cursor.Y - height - 20;
            var panel = new Rectangle(Math.Max(screen.Left + 4, x), Math.Max(screen.Top + 4, y), width, height);
            Theme.Card(g, panel, Theme.Dark);
            var lens = new Rectangle(panel.X + 6, panel.Y + 6, width - 12, 61);
            var source = Rectangle.Intersect(ImageBounds, new Rectangle(cursor.X - 8, cursor.Y - 3, 17, 7));
            var state = g.Save();
            g.InterpolationMode = InterpolationMode.NearestNeighbor;
            g.PixelOffsetMode = PixelOffsetMode.Half;
            g.DrawImage(snapshot.Bitmap, lens, source, GraphicsUnit.Pixel);
            g.Restore(state);
            using (var pen = new Pen(Color.FromArgb(110, 210, 255)))
            {
                float cx = lens.Left + (cursor.X - source.X + .5f) * lens.Width / source.Width;
                float cy = lens.Top + (cursor.Y - source.Y + .5f) * lens.Height / source.Height;
                g.DrawLine(pen, cx, lens.Top, cx, lens.Bottom);
                g.DrawLine(pen, lens.Left, cy, lens.Right, cy);
            }
            Color value = snapshot.Bitmap.GetPixel(cursor.X, cursor.Y);
            Theme.Text(g, $"位置 {cursor.X + snapshot.Bounds.X}, {cursor.Y + snapshot.Bounds.Y}",
                Theme.UiFont, new Rectangle(panel.X + 8, panel.Y + 66, width - 15, 22), Color.White);
            Theme.Text(g, notice ?? $"#{value.R:X2}{value.G:X2}{value.B:X2}  ·  RGB {value.R}, {value.G}, {value.B}",
                Theme.UiFont, new Rectangle(panel.X + 8, panel.Y + 87, width - 15, 22), Color.FromArgb(172, 210, 255));
        }

        void DrawHelp(Graphics g)
        {
            var screen = Screen.FromPoint(MousePosition).Bounds;
            screen.Offset(-snapshot.Bounds.X, -snapshot.Bounds.Y);
            var card = new Rectangle(screen.X + Math.Max(8, (screen.Width - 410) / 2),
                screen.Y + Math.Max(8, (screen.Height - 282) / 2), 410, 282);
            Theme.Card(g, card, Theme.Dark, 14);
            string[] rows =
            {
                "截图快捷键", "拖动框选  ·  Shift 拉正方形  ·  单击吸附窗口",
                "Ctrl+A 全屏  ·  R 恢复上次选区  ·  C 复制颜色",
                "Tab 保留选区以便精调  ·  拖动手柄调整大小",
                "方向键移动  ·  Ctrl+方向键调整大小  ·  Shift 加速",
                "Enter 或双击确认  ·  Esc 退出  ·  F1 关闭帮助"
            };
            for (int i = 0; i < rows.Length; i++)
                Theme.Text(g, rows[i], i == 0 ? Theme.Heading : Theme.UiFont,
                    new Rectangle(card.X + 20, card.Y + 14 + i * 43, card.Width - 40, 40),
                    i == 0 ? Color.White : Color.FromArgb(194, 215, 246));
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                noticeTimer.Dispose();
                snapshot.Dispose();
            }
            base.Dispose(disposing);
        }
    }
}
