using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Linq;
using System.Threading.Tasks;
using System.Windows.Forms;
using SimpleScreenshot.Core;

namespace SimpleScreenshot
{
    sealed class EditorForm : Form
    {
        readonly Bitmap image;
        readonly History<Ink> history = new History<Ink>();
        readonly CaptureAction primary;
        readonly Func<Bitmap, CaptureAction, bool> complete;
        readonly Action<bool> reselect;
        readonly Func<Bitmap, Task<Tuple<string, RectangleF>[]>> runOcr;
        readonly Panel viewport;
        readonly Ribbon ribbon;
        readonly Label status;
        readonly RibbonButton undo, redo;
        readonly Dictionary<InkTool, RibbonButton> tools = new Dictionary<InkTool, RibbonButton>();
        readonly ContextMenuStrip more = new ContextMenuStrip { Renderer = new ToolStripRenderer() };
        readonly ContextMenuStrip styles = new ContextMenuStrip { Renderer = new ToolStripRenderer() };
        readonly OcrLayer ocr;
        InkTool tool = InkTool.Pen;
        Ink active;
        Point mouseOrigin;
        PointF origin;
        float scale = 1, initialScale = 1;
        Color ink = Color.FromArgb(229, 57, 68);
        float width = 4, textSize = 24;
        bool dragged, doubleClick;
        string detail;
        static Color rememberedColor = Color.FromArgb(229, 57, 68);
        static float rememberedWidth = 4, rememberedTextSize = 24;

        internal EditorForm(Bitmap image, CaptureAction primary, Point location, Func<Bitmap, CaptureAction, bool> complete,
            Action<bool> reselect, Func<Bitmap, Task<Tuple<string, RectangleF>[]>> runOcr)
        {
            this.image = image;
            this.primary = primary;
            this.complete = complete;
            this.reselect = reselect;
            this.runOcr = runOcr;
            ink = rememberedColor;
            width = rememberedWidth;
            textSize = rememberedTextSize;
            Text = "截图标注";
            Font = Theme.UiFont;
            AutoScaleMode = AutoScaleMode.None;
            BackColor = Theme.Background;
            KeyPreview = true;
            StartPosition = FormStartPosition.Manual;
            Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);

            viewport = new CanvasPanel { Dock = DockStyle.Fill, BackColor = Theme.Dark, Cursor = Cursors.Cross };
            viewport.Paint += PaintImage;
            viewport.MouseDown += Down;
            viewport.MouseMove += MovePointer;
            viewport.MouseUp += Up;
            viewport.MouseDoubleClick += Double;
            viewport.MouseWheel += Zoom;
            viewport.SizeChanged += (_, __) => viewport.Invalidate();

            ribbon = new Ribbon();
            ribbon.Add("复制", "copy", "复制并关闭（Ctrl+C）", () => Complete(CaptureAction.Copy));
            ribbon.Add("保存", "save", "保存并关闭（Ctrl+S）", () => Complete(CaptureAction.Save));
            ribbon.Add("精调", "crop", "返回同一张桌面快照调整选区", () => Reselect(true));
            AddTool(InkTool.Pen, "画笔", "pen", "自由画笔（P）");
            AddTool(InkTool.Arrow, "箭头", "arrow", "箭头（A，Shift 每 45°）");
            AddTool(InkTool.Rectangle, "矩形", "rect", "矩形（R）");
            RibbonButton moreButton = null;
            moreButton = ribbon.Add("更多", "more", "其他标注工具", () => more.Show(moreButton, new Point(0, moreButton.Height)));
            AddMore(InkTool.Highlight, "荧光笔（G）");
            AddMore(InkTool.Ellipse, "椭圆（O，Shift 正圆）");
            AddMore(InkTool.Number, "序号（N）");
            AddMore(InkTool.Mosaic, "马赛克（M）");
            AddMore(InkTool.Text, "文字（T）");
            more.Items.Add(new ToolStripSeparator());
            more.Items.Add("另存为…（Ctrl+Shift+S）", null, (_, __) => Complete(CaptureAction.SaveAs));
            more.Items.Add("清空标注（Ctrl+D）", null, (_, __) => ClearInk());
            RibbonButton styleButton = null;
            styleButton = ribbon.Add("样式", "style", "颜色、粗细和字号", () => styles.Show(styleButton, new Point(0, styleButton.Height)));
            var colorMenu = new ToolStripMenuItem("颜色");
            foreach (var item in new[]
            {
                Tuple.Create("红色", Color.FromArgb(229, 57, 68)), Tuple.Create("蓝色", Theme.Accent),
                Tuple.Create("绿色", Color.FromArgb(27, 151, 99)), Tuple.Create("黄色", Color.Gold),
                Tuple.Create("白色", Color.White), Tuple.Create("黑色", Color.Black)
            })
                colorMenu.DropDownItems.Add(item.Item1, null, (_, __) => { ink = rememberedColor = item.Item2; UpdateUi(); });
            var widthMenu = new ToolStripMenuItem("画笔粗细");
            foreach (int value in new[] { 2, 4, 6, 9, 13, 18 })
                widthMenu.DropDownItems.Add(value + " 像素", null, (_, __) => { width = rememberedWidth = value; UpdateUi(); });
            var textMenu = new ToolStripMenuItem("文字字号");
            foreach (int value in new[] { 14, 18, 24, 32, 42, 56 })
                textMenu.DropDownItems.Add(value + " 像素", null, (_, __) => { textSize = rememberedTextSize = value; UpdateUi(); });
            styles.Items.AddRange(new ToolStripItem[] { colorMenu, widthMenu, textMenu });
            undo = ribbon.Add("撤销", "undo", "撤销（Ctrl+Z）", Undo);
            redo = ribbon.Add("重做", "redo", "重做（Ctrl+Y）", () => { history.Redo(); UpdateUi(); });
            ribbon.Add("识别", "ocr", "识别文字（W）", StartOcr);
            var header = new Panel { Dock = DockStyle.Top, Height = 52, Padding = new Padding(7), AutoScroll = true };
            ribbon.Location = new Point(7, 6);
            header.Controls.Add(ribbon);
            status = new Label { Dock = DockStyle.Bottom, Height = 28, Font = Theme.UiFont,
                ForeColor = Theme.Muted, Padding = new Padding(8, 0, 0, 0), TextAlign = ContentAlignment.MiddleLeft };
            var body = new Panel { Dock = DockStyle.Fill, Padding = new Padding(6, 0, 6, 0) };
            body.Controls.Add(viewport);
            Controls.Add(body);
            Controls.Add(status);
            Controls.Add(header);
            ocr = new OcrLayer(UpdateUi, value => { detail = value; UpdateUi(); });

            var screen = Screen.FromPoint(location).WorkingArea;
            int desiredWidth = Math.Max(Math.Min(screen.Width - 16, 700), Math.Min(image.Width + 12, screen.Width - 20));
            int desiredHeight = Math.Max(150, Math.Min(image.Height + 80, screen.Height - 60));
            MinimumSize = new Size(300, 180);
            ClientSize = new Size(desiredWidth, desiredHeight);
            Location = new Point(Geometry.Clamp(location.X, screen.Left, Math.Max(screen.Left, screen.Right - Width)),
                Geometry.Clamp(location.Y, screen.Top, Math.Max(screen.Top, screen.Bottom - Height)));
            PerformLayout();
            initialScale = scale = Math.Min(1, Math.Min((float)viewport.Width / image.Width, (float)viewport.Height / image.Height));
            if (scale <= 0) initialScale = scale = 1;
            UpdateUi();
            viewport.Select();
        }

        void AddTool(InkTool mode, string label, string glyph, string tooltip) =>
            tools.Add(mode, ribbon.Add(label, glyph, tooltip, () => SelectTool(mode)));

        void AddMore(InkTool mode, string label) => more.Items.Add(label, null, (_, __) => SelectTool(mode));

        void SelectTool(InkTool value)
        {
            if (ocr.Active) return;
            tool = value;
            UpdateUi();
        }

        void UpdateUi()
        {
            if (IsDisposed) return;
            foreach (var item in tools) item.Value.Selected = item.Key == tool;
            undo.Enabled = history.CanUndo && !ocr.Active;
            redo.Enabled = history.CanRedo && !ocr.Active;
            ribbon.Visible = !ocr.Active;
            viewport.Cursor = ocr.Active ? Cursors.IBeam : Cursors.Cross;
            status.Text = ocr.Active ? detail : $"{image.Width} × {image.Height} 像素  ·  {scale:P0}  ·  滚轮缩放  ·  双击{(primary == CaptureAction.Save ? "保存" : "复制")}";
            viewport.Invalidate();
        }

        RectangleF Destination => new RectangleF((viewport.Width - image.Width * scale) / 2,
            (viewport.Height - image.Height * scale) / 2, image.Width * scale, image.Height * scale);

        PointF ImagePoint(Point position)
        {
            var target = Destination;
            return new PointF((position.X - target.X) / scale, (position.Y - target.Y) / scale);
        }

        void PaintImage(object sender, PaintEventArgs e)
        {
            var g = e.Graphics;
            var rect = Destination;
            g.InterpolationMode = scale == 1 ? InterpolationMode.NearestNeighbor : InterpolationMode.HighQualityBilinear;
            g.PixelOffsetMode = PixelOffsetMode.Half;
            g.DrawImage(image, rect, new Rectangle(Point.Empty, image.Size), GraphicsUnit.Pixel);
            g.TranslateTransform(rect.X, rect.Y);
            g.ScaleTransform(scale, scale);
            g.SetClip(new Rectangle(Point.Empty, image.Size));
            if (ocr.Active) ocr.Draw(g, scale);
            else
            {
                foreach (var command in history.Items) command.Draw(g, image);
                active?.Draw(g, image);
            }
        }

        void Down(object sender, MouseEventArgs e)
        {
            if (e.Button == MouseButtons.Right) { StepBack(); return; }
            if (e.Button != MouseButtons.Left) return;
            PointF point = ImagePoint(e.Location);
            if (ocr.Active) { ocr.Down(point); return; }
            if (!Destination.Contains(e.Location)) return;
            mouseOrigin = e.Location;
            origin = point;
            dragged = doubleClick = false;
            if (tool != InkTool.Text && tool != InkTool.Number)
                active = new Ink { Tool = tool, Start = point, End = point, Color = tool == InkTool.Highlight &&
                    ink == Color.FromArgb(229, 57, 68) ? Color.Gold : ink,
                    Width = tool == InkTool.Highlight ? width * 4 : width,
                    Points = new List<PointF> { point } };
            viewport.Capture = true;
        }

        bool BeyondDrag(Point value)
        {
            var threshold = SystemInformation.DragSize;
            return Math.Abs(value.X - mouseOrigin.X) >= threshold.Width / 2 ||
                Math.Abs(value.Y - mouseOrigin.Y) >= threshold.Height / 2;
        }

        void MovePointer(object sender, MouseEventArgs e)
        {
            if (ocr.Active) { ocr.Move(ImagePoint(e.Location)); return; }
            if (!viewport.Capture || e.Button != MouseButtons.Left) return;
            dragged |= BeyondDrag(e.Location);
            if (dragged && active != null)
            {
                var point = Constrained(ImagePoint(e.Location));
                active.End = point;
                if (tool == InkTool.Pen || tool == InkTool.Highlight) active.Points.Add(point);
                viewport.Invalidate();
            }
        }

        PointF Constrained(PointF point)
        {
            if ((ModifierKeys & Keys.Shift) == 0) return point;
            float x = point.X - origin.X, y = point.Y - origin.Y;
            if (tool == InkTool.Arrow)
            {
                double angle = Math.Round(Math.Atan2(y, x) / (Math.PI / 4)) * Math.PI / 4;
                double length = Math.Sqrt(x * x + y * y);
                return new PointF(origin.X + (float)(length * Math.Cos(angle)), origin.Y + (float)(length * Math.Sin(angle)));
            }
            if (tool == InkTool.Rectangle || tool == InkTool.Ellipse)
            {
                float side = Math.Max(Math.Abs(x), Math.Abs(y));
                return new PointF(origin.X + (x < 0 ? -side : side), origin.Y + (y < 0 ? -side : side));
            }
            return point;
        }

        void Up(object sender, MouseEventArgs e)
        {
            if (e.Button != MouseButtons.Left) return;
            if (ocr.Active) { ocr.Up(ImagePoint(e.Location)); return; }
            if (!viewport.Capture) return;
            viewport.Capture = false;
            dragged |= BeyondDrag(e.Location);
            if (doubleClick && !dragged && tool != InkTool.Text && tool != InkTool.Number)
            {
                active = null;
                Complete(primary);
                return;
            }
            if (active != null && dragged)
            {
                var point = Constrained(ImagePoint(e.Location));
                active.End = point;
                active.Points.Add(point);
                if (tool != InkTool.Rectangle && tool != InkTool.Ellipse && tool != InkTool.Mosaic ||
                    active.Bounds.Width >= 2 && active.Bounds.Height >= 2)
                    history.Push(active);
            }
            active = null;
            if (!dragged && tool == InkTool.Number)
            {
                int next = history.Items.Count(command => command.Tool == InkTool.Number) + 1;
                history.Push(new Ink { Tool = tool, Start = origin, Color = ink, Width = width, Text = next.ToString() });
            }
            if (!dragged && tool == InkTool.Text)
            {
                string text = TextDialog.Read(this);
                if (!string.IsNullOrWhiteSpace(text))
                    history.Push(new Ink { Tool = tool, Start = origin, Color = ink, Width = textSize, Text = text });
            }
            UpdateUi();
        }

        void Double(object sender, MouseEventArgs e)
        {
            if (e.Button != MouseButtons.Left) return;
            if (ocr.Active) ocr.Double(ImagePoint(e.Location));
            else doubleClick = true;
        }

        void Zoom(object sender, MouseEventArgs e)
        {
            if (ocr.Active) return;
            if ((ModifierKeys & Keys.Control) != 0)
            {
                int step = Math.Sign(e.Delta);
                if (tool == InkTool.Text) textSize = rememberedTextSize = Math.Max(12, Math.Min(90, textSize + step * 2));
                else width = rememberedWidth = Math.Max(1, Math.Min(36, width + step));
                UpdateUi();
                return;
            }
            scale = Math.Max(Math.Min(initialScale, .2f), Math.Min(5, scale * (float)Math.Pow(1.1, e.Delta / 120.0)));
            UpdateUi();
        }

        void ClearInk()
        {
            active = null;
            history.Clear();
            UpdateUi();
        }

        void Undo()
        {
            if (active != null) { active = null; viewport.Capture = false; }
            else history.Undo();
            UpdateUi();
        }

        void StepBack()
        {
            if (ocr.Active) ocr.End();
            else if (active != null || history.CanUndo) Undo();
            else Reselect(false);
        }

        void Reselect(bool precise)
        {
            if (ocr.Active) return;
            if (history.CanUndo && MessageBox.Show(this, "调整选区将清除当前标注。继续吗？", "精调选区",
                MessageBoxButtons.OKCancel, MessageBoxIcon.Question) != DialogResult.OK) return;
            reselect(precise);
        }

        void Complete(CaptureAction action)
        {
            using (var output = Ink.Render(image, history.Items))
                if (complete(output, action)) Close();
        }

        void StartOcr() => ocr.Start(() => runOcr(image));

        protected override bool ProcessCmdKey(ref Message m, Keys data)
        {
            if (ocr.Active) return ocr.Key(data);
            switch (data)
            {
                case Keys.W: StartOcr(); return true;
                case Keys.Escape: StepBack(); return true;
                case Keys.Control | Keys.Z: Undo(); return true;
                case Keys.Control | Keys.Y: history.Redo(); UpdateUi(); return true;
                case Keys.Control | Keys.C: Complete(CaptureAction.Copy); return true;
                case Keys.Control | Keys.S: Complete(CaptureAction.Save); return true;
                case Keys.Control | Keys.Shift | Keys.S: Complete(CaptureAction.SaveAs); return true;
                case Keys.Control | Keys.D: ClearInk(); return true;
                case Keys.Enter: Complete(primary); return true;
            }
            switch (data)
            {
                case Keys.P: SelectTool(InkTool.Pen); return true;
                case Keys.G: SelectTool(InkTool.Highlight); return true;
                case Keys.A: SelectTool(InkTool.Arrow); return true;
                case Keys.R: SelectTool(InkTool.Rectangle); return true;
                case Keys.O: SelectTool(InkTool.Ellipse); return true;
                case Keys.N: SelectTool(InkTool.Number); return true;
                case Keys.M: SelectTool(InkTool.Mosaic); return true;
                case Keys.T: SelectTool(InkTool.Text); return true;
            }
            return base.ProcessCmdKey(ref m, data);
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                ocr?.End();
                image.Dispose();
                more.Dispose();
                styles.Dispose();
            }
            base.Dispose(disposing);
        }
    }

    sealed class CanvasPanel : Panel
    {
        internal CanvasPanel()
        {
            DoubleBuffered = true;
            SetStyle(ControlStyles.StandardClick | ControlStyles.StandardDoubleClick | ControlStyles.Selectable, true);
        }
    }

    static class TextDialog
    {
        internal static string Read(IWin32Window owner)
        {
            using (var window = new Form { Text = "添加文字", StartPosition = FormStartPosition.CenterParent,
                FormBorderStyle = FormBorderStyle.FixedDialog, MinimizeBox = false, MaximizeBox = false, ShowInTaskbar = false,
                ClientSize = new Size(358, 172), Font = Theme.UiFont, BackColor = Theme.Background, Padding = new Padding(12) })
            {
                var input = new TextBox { Multiline = true, Dock = DockStyle.Fill, ScrollBars = ScrollBars.Vertical };
                var buttons = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 38,
                    FlowDirection = FlowDirection.RightToLeft, Padding = new Padding(0, 5, 0, 0) };
                var ok = new Button { Text = "添加", DialogResult = DialogResult.OK };
                var cancel = new Button { Text = "取消", DialogResult = DialogResult.Cancel };
                buttons.Controls.Add(ok);
                buttons.Controls.Add(cancel);
                window.Controls.Add(input);
                window.Controls.Add(buttons);
                window.CancelButton = cancel;
                return window.ShowDialog(owner) == DialogResult.OK ? input.Text : null;
            }
        }
    }
}
