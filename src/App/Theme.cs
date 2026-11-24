using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Windows.Forms;

namespace SimpleScreenshot
{
    static class Theme
    {
        internal static readonly Color Background = Color.FromArgb(241, 244, 249);
        internal static readonly Color Paper = Color.FromArgb(255, 255, 255);
        internal static readonly Color Ink = Color.FromArgb(32, 43, 62);
        internal static readonly Color Muted = Color.FromArgb(86, 101, 126);
        internal static readonly Color Accent = Color.FromArgb(18, 104, 220);
        internal static readonly Color AccentTint = Color.FromArgb(223, 237, 255);
        internal static readonly Color Border = Color.FromArgb(218, 225, 236);
        internal static readonly Color Dark = Color.FromArgb(30, 39, 55);
        internal static readonly Font UiFont = new Font("Microsoft YaHei UI", 9);
        internal static readonly Font Heading = new Font("Microsoft YaHei UI", 13, FontStyle.Bold);

        internal static GraphicsPath Round(Rectangle r, int radius)
        {
            var p = new GraphicsPath();
            int d = radius * 2;
            if (r.Width <= d || r.Height <= d)
            {
                p.AddRectangle(r);
                return p;
            }
            p.AddArc(r.Left, r.Top, d, d, 180, 90);
            p.AddArc(r.Right - d, r.Top, d, d, 270, 90);
            p.AddArc(r.Right - d, r.Bottom - d, d, d, 0, 90);
            p.AddArc(r.Left, r.Bottom - d, d, d, 90, 90);
            p.CloseFigure();
            return p;
        }

        internal static void Card(Graphics g, Rectangle bounds, Color color, int radius = 9)
        {
            using (var path = Round(bounds, radius))
            using (var brush = new SolidBrush(color))
                g.FillPath(brush, path);
        }

        internal static void Text(Graphics graphics, string value, Font font, Rectangle bounds, Color color, bool center = false)
        {
            TextRenderer.DrawText(graphics, value, font, bounds, color,
                TextFormatFlags.NoPrefix | TextFormatFlags.EndEllipsis | TextFormatFlags.VerticalCenter |
                TextFormatFlags.SingleLine | (center ? TextFormatFlags.HorizontalCenter : TextFormatFlags.Left));
        }

        internal static void Icon(Graphics g, string kind, Point center, Color color)
        {
            var state = g.Save();
            g.TranslateTransform(center.X - 8, center.Y - 8);
            g.SmoothingMode = SmoothingMode.AntiAlias;
            using (var p = new Pen(color, 1.5f) { StartCap = LineCap.Round, EndCap = LineCap.Round, LineJoin = LineJoin.Round })
            {
                void Line(params Point[] points) => g.DrawLines(p, points);
                Point P(int x, int y) => new Point(x, y);
                switch (kind)
                {
                    case "copy": g.DrawRectangle(p, 5, 5, 9, 9); Line(P(2, 10), P(2, 2), P(10, 2)); break;
                    case "save": g.DrawRectangle(p, 2, 2, 12, 12); Line(P(5, 2), P(5, 6), P(11, 6), P(11, 2)); g.DrawRectangle(p, 5, 9, 6, 5); break;
                    case "pin": Line(P(4, 3), P(12, 3), P(10, 6), P(12, 10), P(4, 10), P(6, 6), P(4, 3)); Line(P(8, 10), P(8, 15)); break;
                    case "rect": g.DrawRectangle(p, 2, 4, 12, 8); break;
                    case "ellipse": g.DrawEllipse(p, 2, 4, 12, 8); break;
                    case "arrow": Line(P(2, 13), P(13, 3), P(8, 3)); Line(P(13, 3), P(13, 8)); break;
                    case "pen": case "highlight": Line(P(2, 14), P(4, 9), P(11, 2), P(14, 5), P(7, 12), P(2, 14)); break;
                    case "crop": Line(P(4, 1), P(4, 12), P(15, 12)); Line(P(1, 4), P(12, 4), P(12, 15)); break;
                    case "ocr": Line(P(1, 6), P(1, 2), P(5, 2)); Line(P(11, 2), P(15, 2), P(15, 6));
                        Line(P(1, 10), P(1, 14), P(5, 14)); Line(P(11, 14), P(15, 14), P(15, 10)); Line(P(5, 7), P(11, 7)); Line(P(5, 10), P(9, 10)); break;
                    case "undo": Line(P(6, 3), P(2, 7), P(6, 11)); g.DrawArc(p, 2, 7, 11, 8, 180, 130); break;
                    case "redo": Line(P(10, 3), P(14, 7), P(10, 11)); g.DrawArc(p, 3, 7, 11, 8, 230, 130); break;
                    case "more": for (int x = 3; x <= 13; x += 5) g.DrawEllipse(p, x - 1, 7, 2, 2); break;
                    case "style": Line(P(2, 4), P(14, 4)); Line(P(2, 8), P(14, 8)); Line(P(2, 12), P(14, 12)); g.DrawEllipse(p, 4, 3, 2, 2); g.DrawEllipse(p, 9, 7, 2, 2); break;
                    default: Line(P(3, 8), P(13, 8)); Line(P(8, 3), P(8, 13)); break;
                }
            }
            g.Restore(state);
        }
    }

    sealed class ToolStripRenderer : ToolStripProfessionalRenderer
    {
        internal ToolStripRenderer() : base(new Palette()) { RoundedEdges = false; }
        sealed class Palette : ProfessionalColorTable
        {
            public override Color ToolStripDropDownBackground => Theme.Paper;
            public override Color MenuBorder => Theme.Border;
            public override Color MenuItemBorder => Theme.AccentTint;
            public override Color MenuItemSelected => Theme.AccentTint;
            public override Color ImageMarginGradientBegin => Theme.Paper;
            public override Color ImageMarginGradientMiddle => Theme.Paper;
            public override Color ImageMarginGradientEnd => Theme.Paper;
        }
    }

    sealed class Ribbon : FlowLayoutPanel
    {
        readonly ToolTip tips = new ToolTip { ShowAlways = true };
        internal Ribbon()
        {
            DoubleBuffered = true;
            AutoSize = true;
            AutoSizeMode = AutoSizeMode.GrowAndShrink;
            WrapContents = false;
            Padding = new Padding(4);
            BackColor = Theme.Paper;
        }

        protected override void OnSizeChanged(EventArgs args)
        {
            base.OnSizeChanged(args);
            if (Width <= 0 || Height <= 0) return;
            var previous = Region;
            using (var path = Theme.Round(ClientRectangle, 10)) Region = new Region(path);
            previous?.Dispose();
        }

        internal RibbonButton Add(string label, string glyph, string tooltip, Action clicked)
        {
            var button = new RibbonButton(label, glyph);
            button.Click += (_, __) => clicked();
            tips.SetToolTip(button, tooltip);
            Controls.Add(button);
            return button;
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) tips.Dispose();
            base.Dispose(disposing);
        }
    }

    sealed class RibbonButton : Button
    {
        readonly string glyph;
        bool selected;
        bool hover;

        internal RibbonButton(string label, string glyph)
        {
            this.glyph = glyph;
            Text = label;
            AccessibleName = label;
            Font = Theme.UiFont;
            Margin = new Padding(1);
            Size = new Size(label.Length > 2 ? 78 : 57, 34);
            FlatStyle = FlatStyle.Flat;
            FlatAppearance.BorderSize = 0;
            Cursor = Cursors.Hand;
        }

        internal bool Selected
        {
            get => selected;
            set { selected = value; Invalidate(); }
        }

        protected override void OnMouseEnter(EventArgs e) { hover = true; Invalidate(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { hover = false; Invalidate(); base.OnMouseLeave(e); }

        protected override void OnPaint(PaintEventArgs e)
        {
            var g = e.Graphics;
            g.Clear(Theme.Paper);
            g.SmoothingMode = SmoothingMode.AntiAlias;
            if (selected || hover || Focused)
                Theme.Card(g, ClientRectangle, Theme.AccentTint, 7);
            var ink = !Enabled ? Theme.Muted : selected || hover ? Theme.Accent : Theme.Ink;
            Theme.Icon(g, glyph, new Point(12, Height / 2), ink);
            Theme.Text(g, Text, Font, new Rectangle(23, 0, Width - 23, Height), ink);
            if (Focused) ControlPaint.DrawFocusRectangle(g, Rectangle.Inflate(ClientRectangle, -3, -3));
        }
    }
}
