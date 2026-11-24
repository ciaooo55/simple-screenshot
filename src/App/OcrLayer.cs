using System;
using System.Drawing;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace SimpleScreenshot
{
    sealed class OcrLayer
    {
        readonly Action redraw;
        readonly Action<string> status;
        Tuple<string, RectangleF>[] spans;
        int anchor = -1, focus = -1, generation;
        bool dragging;
        internal bool Active { get; private set; }
        internal bool Loading { get; private set; }

        internal OcrLayer(Action redraw, Action<string> status)
        {
            this.redraw = redraw;
            this.status = status;
        }

        internal async void Start(Func<Task<Tuple<string, RectangleF>[]>> run)
        {
            if (Active) return;
            Active = true;
            Loading = true;
            int token = ++generation;
            status("正在本机识别文字…");
            redraw();
            try
            {
                var result = await run();
                if (token != generation) return;
                spans = result;
                status(result.Length == 0 ? "未识别到文字（Esc 返回）" : "拖选文字 · 双击选词 · Ctrl+A 全选 · Ctrl+C 复制");
            }
            catch (Exception error)
            {
                if (token != generation) return;
                Log.Write(error);
                status(error.Message);
            }
            finally
            {
                if (token == generation)
                {
                    Loading = false;
                    redraw();
                }
            }
        }

        internal void End()
        {
            generation++;
            Active = false;
            Loading = false;
            spans = null;
            anchor = focus = -1;
            dragging = false;
            redraw();
        }

        int Hit(PointF p)
        {
            if (spans == null) return -1;
            for (int index = 0; index < spans.Length; index++)
            {
                var box = spans[index].Item2;
                if (box.Width == 0 || box.Height == 0) continue;
                box.Inflate(1, 2);
                if (box.Contains(p)) return index;
            }
            return -1;
        }

        internal void Down(PointF p)
        {
            anchor = focus = Hit(p);
            dragging = anchor >= 0;
            redraw();
        }

        internal void Move(PointF p)
        {
            if (!dragging) return;
            int next = Hit(p);
            if (next >= 0) { focus = next; redraw(); }
        }

        internal void Up(PointF p) { Move(p); dragging = false; }

        internal void Double(PointF p)
        {
            int index = Hit(p);
            if (index < 0) return;
            dragging = false;
            anchor = focus = index;
            bool Latin(string value) => value.Length > 0 && value.All(c => c < 128 &&
                (char.IsLetterOrDigit(c) || c == '_' || c == '-' || c == '\''));
            if (Latin(spans[index].Item1))
            {
                while (anchor > 0 && Latin(spans[anchor - 1].Item1)) anchor--;
                while (focus + 1 < spans.Length && Latin(spans[focus + 1].Item1)) focus++;
            }
            redraw();
        }

        internal bool Key(Keys data)
        {
            if (data == Keys.Escape) { End(); return true; }
            if (spans == null) return true;
            if (data == (Keys.Control | Keys.A) && spans.Length > 0)
            {
                anchor = 0;
                focus = spans.Length - 1;
                redraw();
            }
            else if ((data == (Keys.Control | Keys.C) || data == Keys.Enter) && anchor >= 0)
            {
                var buffer = new StringBuilder();
                for (int index = Math.Min(anchor, focus); index <= Math.Max(anchor, focus); index++)
                    buffer.Append(spans[index].Item1);
                if (buffer.Length > 0)
                {
                    try { Clipboard.SetText(buffer.ToString()); status("已复制识别文字"); }
                    catch (Exception error) { Log.Write(error); status("无法访问剪贴板"); }
                }
            }
            return true;
        }

        internal void Draw(Graphics graphics, float scale)
        {
            if (spans == null) return;
            int first = Math.Min(anchor, focus), end = Math.Max(anchor, focus);
            using (var tint = new SolidBrush(Color.FromArgb(26, Theme.Accent)))
            using (var selected = new SolidBrush(Color.FromArgb(118, Theme.Accent)))
            using (var outline = new Pen(Color.FromArgb(118, Theme.Accent), 1 / Math.Max(.01f, scale)))
            {
                for (int index = 0; index < spans.Length; index++)
                {
                    var box = spans[index].Item2;
                    if (box.Width <= 0 || box.Height <= 0) continue;
                    graphics.FillRectangle(index >= first && index <= end ? selected : tint, box);
                    graphics.DrawRectangle(outline, box.X, box.Y, box.Width, box.Height);
                }
            }
        }
    }
}
