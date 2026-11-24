using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;

namespace SimpleScreenshot.Core
{
    public readonly struct Hotkey : IEquatable<Hotkey>
    {
        static readonly string[] Modifiers = { "Ctrl", "Alt", "Shift", "Win" };
        static readonly int[] ModifierBits = { 2, 1, 4, 8 };
        static readonly Dictionary<int, string> Special = new Dictionary<int, string>
        {
            [0x08] = "Backspace", [0x09] = "Tab", [0x0D] = "Enter", [0x1B] = "Esc",
            [0x20] = "Space", [0x21] = "PageUp", [0x22] = "PageDown", [0x23] = "End",
            [0x24] = "Home", [0x25] = "Left", [0x26] = "Up", [0x27] = "Right",
            [0x28] = "Down", [0x2C] = "PrintScreen", [0x2D] = "Insert", [0x2E] = "Delete"
        };

        public int ModifierMask { get; }
        public int VirtualKey { get; }
        string KeyName { get; }

        public Hotkey(int modifiers, int key)
        {
            if ((modifiers & ~15) != 0)
                throw new ArgumentException("快捷键修饰键无效。");
            if (modifiers == 0 && key != 0x2C && (key < 0x70 || key > 0x87))
                throw new ArgumentException("请搭配 Ctrl、Alt、Shift 或 Win；F1–F24 和 PrintScreen 可以单独使用。");
            if (key >= 0x70 && key <= 0x87)
                KeyName = "F" + (key - 0x6F).ToString(CultureInfo.InvariantCulture);
            else if ((key >= 'A' && key <= 'Z') || (key >= '0' && key <= '9'))
                KeyName = ((char)key).ToString();
            else if (Special.TryGetValue(key, out string name))
                KeyName = name;
            else
                throw new ArgumentException("这个按键暂不支持，请换一个快捷键。");
            ModifierMask = modifiers;
            VirtualKey = key;
        }

        public static Hotkey Parse(string input)
        {
            int mask = 0, key = 0;
            foreach (string part in (input ?? "").Split('+').Select(p => p.Trim()).Where(p => p.Length > 0))
            {
                string token = part.ToUpperInvariant().Replace(" ", "");
                switch (token)
                {
                    case "ALT": mask |= 1; continue;
                    case "CTRL": case "CONTROL": mask |= 2; continue;
                    case "SHIFT": mask |= 4; continue;
                    case "WIN": case "WINDOWS": case "META": mask |= 8; continue;
                }
                if (key != 0)
                    throw new ArgumentException("快捷键只能包含一个主键。");
                if (token.Length == 1)
                    key = token[0];
                else if (token[0] == 'F' && int.TryParse(token.Substring(1), out int function) && function >= 1 && function <= 24)
                    key = 0x6F + function;
                else
                    key = Special.FirstOrDefault(pair => string.Equals(
                        pair.Value, token == "ESCAPE" ? "ESC" : token, StringComparison.OrdinalIgnoreCase)).Key;
                if (key == 0)
                    throw new ArgumentException("不支持的主键：" + part);
            }
            if (key == 0)
                throw new ArgumentException("请同时按下一个非修饰键。");
            return new Hotkey(mask, key);
        }

        public override string ToString()
        {
            int mask = ModifierMask;
            return string.Join("+", Modifiers.Where((_, i) => (mask & ModifierBits[i]) != 0).Concat(new[] { KeyName }));
        }
        public bool Equals(Hotkey other) => ModifierMask == other.ModifierMask && VirtualKey == other.VirtualKey;
        public override bool Equals(object obj) => obj is Hotkey other && Equals(other);
        public override int GetHashCode() => (ModifierMask << 8) ^ VirtualKey;
    }
}
