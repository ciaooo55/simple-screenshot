using System.Collections.Generic;

namespace SimpleScreenshot.Core
{
    public sealed class History<T>
    {
        readonly List<T> items = new List<T>();
        int count;
        public IEnumerable<T> Items
        {
            get { for (int i = 0; i < count; ++i) yield return items[i]; }
        }
        public bool CanUndo => count > 0;
        public bool CanRedo => count < items.Count;

        public void Push(T item)
        {
            if (CanRedo)
                items.RemoveRange(count, items.Count - count);
            items.Add(item);
            count++;
        }
        public void Undo() { if (CanUndo) count--; }
        public void Redo() { if (CanRedo) count++; }
        public void Clear() { items.Clear(); count = 0; }
    }
}
