using System;
using System.Collections.Specialized;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Globalization;
using System.Threading.Tasks;
using System.Windows.Forms;
using SimpleScreenshot.Core;

namespace SimpleScreenshot
{
    sealed class PinForm : Form
    {
        readonly Bitmap image;
        readonly History<Ink> history = new History<Ink>();
        readonly Func<Bitmap, bool, bool?> save;
        readonly Action closeAll;
        readonly Func<Bitmap, Task<Tuple<string, RectangleF>[]>> runOcr;
        readonly OcrLayer ocr;
        readonly Timer hudTimer = new Timer { Interval = 1100 };
        Ink stroke;
        Point mouseDown, startPosition;
        MouseButtons moveButton;
        bool draw = true, moved, fileDragging, clickThrough;
        float zoom = 1, minZoom;
        double beforeThrough = 1;
        string hud;

        internal PinForm(Bitmap image, Point location, bool fit, Func<Bitmap, bool, bool?> save,
            Action closeAll, Func<Bitmap, Task<Tuple<string, RectangleF>[]>> runOcr)
        {
            this.image = image;
            this.save = save;
            this.closeAll = closeAll;
            this.runOcr = runOcr;
            Text = "置顶贴图";
            AutoScaleMode = AutoScaleMode.None;
            StartPosition = FormStartPosition.Manual;
            FormBorderStyle = FormBorderStyle.None;
            TopMost = true;
            ShowInTaskbar = false;
            DoubleBuffered = true;
            KeyPreview = true;
            Cursor = Cursors.Cross;
            Location = location;
            ClientSize = image.Size;
            minZoom = Math.Min(1, Math.Max(.2f, 48f / Math.Min(image.Width, image.Height)));
            ocr = new OcrLayer(Invalidate, value => ShowHud(value, false));
            hudTimer.Tick += (_, __) => { hudTimer.Stop(); hud = null; Invalidate(); };
            if (fit)
            {
                var bounds = Screen.FromPoint(location).WorkingArea;
                float fitZoom = Math.Min(1, Math.Min(bounds.Width * .9f / image.Width, bounds.Height * .9f / image.Height));
                minZoom = Math.Min(minZoom, fitZoom);
                SetZoom(fitZoom, Point.Empty, false);
                Location = new Point(Geometry.Clamp(location.X, bounds.Left, bounds.Right - Width),
                    Geometry.Clamp(location.Y, bounds.Top, bounds.Bottom - Height));
            }
        }

        protected override CreateParams CreateParams
        {
            get
            {
                var parameters = base.CreateParams;
                parameters.ExStyle |= 0x80;
                return parameters;
            }
        }

        internal bool ClickThrough => clickThrough;

        internal void SetClickThrough(bool value)
        {
            if (value == clickThrough || IsDisposed) return;
            if (value)
            {
                if (ocr.Active) EndOcr();
                beforeThrough = Opacity;
                if (Opacity >= 1) Opacity = .99;
                Native.SetWindowLong(Handle, Native.ExtendedStyle,
                    Native.GetWindowLong(Handle, Native.ExtendedStyle) | Native.Transparent);
                ShowHud("已开启鼠标穿透");
            }
            else
            {
                Native.SetWindowLong(Handle, Native.ExtendedStyle,
                    Native.GetWindowLong(Handle, Native.ExtendedStyle) & ~Native.Transparent);
                Opacity = beforeThrough;
                ShowHud("已恢复鼠标点击");
            }
            clickThrough = value;
        }

        internal void ShowHint() => ShowHud("左键画笔  ·  中键移动  ·  右键菜单");

        void ShowHud(string message, bool temporary = true)
        {
            hud = message;
            hudTimer.Stop();
            if (temporary) hudTimer.Start();
            Invalidate();
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            var g = e.Graphics;
            g.InterpolationMode = zoom == 1 ? InterpolationMode.NearestNeighbor : InterpolationMode.HighQualityBilinear;
            g.PixelOffsetMode = PixelOffsetMode.Half;
            g.DrawImage(image, ClientRectangle, new Rectangle(Point.Empty, image.Size), GraphicsUnit.Pixel);
            var state = g.Save();
            g.ScaleTransform(zoom, zoom);
            if (ocr.Active) ocr.Draw(g, zoom);
            else
            {
                foreach (var command in history.Items) command.Draw(g, image);
                stroke?.Draw(g, image);
            }
            g.Restore(state);
            if (string.IsNullOrEmpty(hud)) return;
            int width = Math.Min(Width - 8, TextRenderer.MeasureText(hud, Theme.UiFont).Width + 20);
            if (width <= 0 || Height < 18) return;
            var position = new Rectangle((Width - width) / 2, ocr.Active ? 4 : Math.Max(3, (Height - 26) / 2), width, 26);
            Theme.Card(g, position, Color.FromArgb(216, Theme.Dark), 7);
            Theme.Text(g, hud, Theme.UiFont, position, Color.White, true);
        }

        PointF Source(Point p) => new PointF(p.X / zoom, p.Y / zoom);

        protected override void OnMouseDown(MouseEventArgs e)
        {
            if (ocr.Active)
            {
                if (e.Button == MouseButtons.Right) EndOcr();
                else if (e.Button == MouseButtons.Left) ocr.Down(Source(e.Location));
                return;
            }
            if (e.Button == MouseButtons.Right) return;
            mouseDown = MousePosition;
            startPosition = Location;
            moved = false;
            fileDragging = e.Button == MouseButtons.Left && (ModifierKeys & Keys.Control) != 0;
            if (!fileDragging && (e.Button == MouseButtons.Middle || e.Button == MouseButtons.Left && !draw))
                moveButton = e.Button;
            else if (!fileDragging && e.Button == MouseButtons.Left)
                stroke = new Ink { Tool = InkTool.Pen, Color = Color.FromArgb(230, 56, 68), Width = 3,
                    Points = new System.Collections.Generic.List<PointF> { Source(e.Location) } };
            Capture = e.Button == MouseButtons.Left || e.Button == MouseButtons.Middle;
        }

        protected override void OnMouseMove(MouseEventArgs e)
        {
            if (ocr.Active) { ocr.Move(Source(e.Location)); return; }
            if (!Capture) return;
            var pos = MousePosition;
            int dx = pos.X - mouseDown.X, dy = pos.Y - mouseDown.Y;
            var threshold = SystemInformation.DragSize;
            moved |= Math.Abs(dx) >= threshold.Width / 2 || Math.Abs(dy) >= threshold.Height / 2;
            if (fileDragging && moved)
            {
                fileDragging = false;
                Capture = false;
                try
                {
                    using (var data = Ink.Render(image, history.Items))
                    {
                        var paths = new StringCollection { Output.Drag(data) };
                        var payload = new DataObject();
                        payload.SetFileDropList(paths);
                        DoDragDrop(payload, DragDropEffects.Copy);
                    }
                }
                catch (Exception error) { Log.Write(error); ShowHud("无法拖出 PNG 文件"); }
            }
            else if (moveButton != MouseButtons.None)
                Location = Snap(new Point(startPosition.X + dx, startPosition.Y + dy));
            else if (stroke != null && moved)
            {
                stroke.Points.Add(Source(e.Location));
                Invalidate();
            }
        }

        Point Snap(Point point)
        {
            var work = Screen.FromRectangle(new Rectangle(point, Size)).WorkingArea;
            if (Math.Abs(point.X - work.Left) <= 12) point.X = work.Left;
            else if (Math.Abs(point.X + Width - work.Right) <= 12) point.X = work.Right - Width;
            if (Math.Abs(point.Y - work.Top) <= 12) point.Y = work.Top;
            else if (Math.Abs(point.Y + Height - work.Bottom) <= 12) point.Y = work.Bottom - Height;
            return point;
        }

        protected override void OnMouseUp(MouseEventArgs e)
        {
            if (ocr.Active)
            {
                if (e.Button == MouseButtons.Left) ocr.Up(Source(e.Location));
                return;
            }
            if (e.Button == MouseButtons.Right) { MenuAt(e.Location); return; }
            if (stroke != null && e.Button == MouseButtons.Left)
            {
                if (moved)
                {
                    stroke.Points.Add(Source(e.Location));
                    history.Push(stroke);
                }
                stroke = null;
                Invalidate();
            }
            if (e.Button == moveButton) moveButton = MouseButtons.None;
            fileDragging = false;
            Capture = false;
        }

        protected override void OnMouseDoubleClick(MouseEventArgs e)
        {
            if (e.Button != MouseButtons.Left) return;
            if (ocr.Active) ocr.Double(Source(e.Location));
            else { stroke = null; Reset(); }
        }

        protected override void OnMouseWheel(MouseEventArgs e)
        {
            if (ocr.Active) return;
            if ((ModifierKeys & Keys.Control) != 0)
            {
                Opacity = Math.Max(.2, Math.Min(1, Opacity + e.Delta / 1200.0));
                ShowHud($"不透明度 {Opacity:P0}");
            }
            else SetZoom(zoom * (float)Math.Pow(1.1, e.Delta / 120.0), e.Location, true);
        }

        void SetZoom(float value, Point local, bool feedback)
        {
            value = Math.Max(minZoom, Math.Min(5, value));
            double ratio = value / zoom;
            var point = new Point(Geometry.AnchorOrigin(Left, local.X, ratio), Geometry.AnchorOrigin(Top, local.Y, ratio));
            zoom = value;
            Bounds = new Rectangle(point, new Size(Math.Max(1, (int)Math.Round(image.Width * zoom)),
                Math.Max(1, (int)Math.Round(image.Height * zoom))));
            if (feedback) ShowHud($"缩放 {zoom:P0}");
        }

        void Reset() { SetZoom(1, Point.Empty, false); Opacity = 1; ShowHud("已恢复原始大小和不透明度"); }
        void ToggleDraw() { draw = !draw; Cursor = draw ? Cursors.Cross : Cursors.SizeAll; ShowHud(draw ? "画笔已开启" : "画笔已暂停"); }
        void Undo() { history.Undo(); Invalidate(); }

        void WriteImage(bool toClipboard, bool asFile = false)
        {
            using (var result = Ink.Render(image, history.Items))
            {
                try
                {
                    if (toClipboard) { Clipboard.SetImage(result); ShowHud("已复制图片"); }
                    else
                    {
                        bool? written = save(result, asFile);
                        if (written.HasValue && !IsDisposed) ShowHud(written.Value ? "图片已保存" : "保存失败，已尝试复制到剪贴板");
                    }
                }
                catch (Exception error) { Log.Write(error); ShowHud("操作失败：" + error.Message); }
            }
        }

        void StartOcr()
        {
            Cursor = Cursors.IBeam;
            ocr.Start(() => runOcr(image));
        }

        void EndOcr()
        {
            ocr.End();
            Cursor = draw ? Cursors.Cross : Cursors.SizeAll;
            hud = null;
            Invalidate();
        }

        void MenuAt(Point point)
        {
            var menu = new ContextMenuStrip { Renderer = new ToolStripRenderer(), Font = Theme.UiFont };
            menu.Closed += (_, __) => menu.Dispose();
            menu.Items.Add($"缩放 {zoom:P0}  ·  不透明度 {Opacity:P0}").Enabled = false;
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add("复制图片  Ctrl+C", null, (_, __) => WriteImage(true));
            menu.Items.Add("保存图片  Ctrl+S", null, (_, __) => WriteImage(false));
            menu.Items.Add("另存为…  Ctrl+Shift+S", null, (_, __) => WriteImage(false, true));
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add("撤销一笔", null, (_, __) => Undo()).Enabled = history.CanUndo;
            menu.Items.Add(draw ? "暂停画笔  P" : "启用画笔  P", null, (_, __) => ToggleDraw());
            menu.Items.Add("识别文字  W", null, (_, __) => StartOcr());
            menu.Items.Add("拖出 PNG：Ctrl+拖动").Enabled = false;
            menu.Items.Add("恢复原始大小  Ctrl+0", null, (_, __) => Reset());
            menu.Items.Add("鼠标穿透（从托盘恢复）", null, (_, __) => SetClickThrough(true));
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add("关闭贴图  Esc", null, (_, __) => Close());
            menu.Items.Add("关闭所有贴图", null, (_, __) => closeAll());
            menu.Show(this, point);
        }

        protected override bool ProcessCmdKey(ref Message m, Keys data)
        {
            if (ocr.Active)
            {
                if (data == Keys.Escape) { EndOcr(); return true; }
                return ocr.Key(data);
            }
            var key = data & Keys.KeyCode;
            int distance = (data & Keys.Shift) == 0 ? 1 : 10;
            switch (data)
            {
                case Keys.Escape: Close(); return true;
                case Keys.W: StartOcr(); return true;
                case Keys.P: ToggleDraw(); return true;
                case Keys.Control | Keys.C: WriteImage(true); return true;
                case Keys.Control | Keys.S: WriteImage(false); return true;
                case Keys.Control | Keys.Shift | Keys.S: WriteImage(false, true); return true;
                case Keys.Control | Keys.D0:
                case Keys.Control | Keys.NumPad0: Reset(); return true;
                case Keys.Control | Keys.Z: Undo(); return true;
            }
            switch (key)
            {
                case Keys.Oemplus: case Keys.Add: SetZoom(zoom * 1.1f, new Point(Width / 2, Height / 2), true); return true;
                case Keys.OemMinus: case Keys.Subtract: SetZoom(zoom / 1.1f, new Point(Width / 2, Height / 2), true); return true;
                case Keys.Left: Left -= distance; return true;
                case Keys.Right: Left += distance; return true;
                case Keys.Up: Top -= distance; return true;
                case Keys.Down: Top += distance; return true;
            }
            return base.ProcessCmdKey(ref m, data);
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) { ocr?.End(); hudTimer.Dispose(); image.Dispose(); }
            base.Dispose(disposing);
        }
    }
}
