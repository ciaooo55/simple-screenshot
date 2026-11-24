using System;
using System.Drawing;
using System.IO;
using System.Text;
using SimpleScreenshot.Core;
using Xunit;

namespace SimpleScreenshot.Tests
{
    public class CoreTests
    {
        static Settings Decode(string json) => SettingsStore.Decode(
            new MemoryStream(Encoding.UTF8.GetBytes(json)), Settings.Defaults("app"));

        [Theory]
        [InlineData(1)]
        [InlineData(2)]
        public void MigratesPreviousSettingsWithoutShortcutConflict(int version)
        {
            var settings = Decode($"{{\"version\":{version},\"copy_hotkey\":\"alt+q\",\"hide_pins_on_capture\":true}}");
            Assert.Equal(3, settings.Version);
            Assert.Equal("Alt+Q", settings.CopyHotkey);
            Assert.Equal("Alt+W", settings.PinHotkey);
            Assert.False(settings.HidePinsOnCapture);
            Assert.Equal(Path.Combine("app", "tp"), settings.SaveDirectory);
        }

        [Fact]
        public void KeepsVersionThreePreferences()
        {
            var settings = Decode("{\"version\":3,\"hide_pins_on_capture\":true,\"start_with_windows\":true}");
            Assert.True(settings.HidePinsOnCapture);
            Assert.True(settings.StartWithWindows);
        }

        [Theory]
        [InlineData("[]")]
        [InlineData("{\"start_with_windows\":\"true\"}")]
        [InlineData("{\"save_directory\":null}")]
        [InlineData("{\"version\":12}")]
        public void RejectsInvalidSettingsRatherThanCoercingThem(string json) =>
            Assert.Throws<System.Runtime.Serialization.SerializationException>(() => Decode(json));

        [Theory]
        [InlineData("print screen", "PrintScreen", 0, 44)]
        [InlineData("windows+shift+f24", "Shift+Win+F24", 12, 135)]
        [InlineData("control+alt+a", "Ctrl+Alt+A", 3, 65)]
        public void ParsesHotkey(string value, string text, int modifiers, int key)
        {
            Hotkey parsed = Hotkey.Parse(value);
            Assert.Equal(text, parsed.ToString());
            Assert.Equal(modifiers, parsed.ModifierMask);
            Assert.Equal(key, parsed.VirtualKey);
        }

        [Theory]
        [InlineData("A")]
        [InlineData("F25")]
        [InlineData("Ctrl")]
        [InlineData("Alt+A+S")]
        public void RejectsUnsupportedHotkey(string value) => Assert.Throws<ArgumentException>(() => Hotkey.Parse(value));

        [Fact]
        public void AddsTimestampAndCollisionSuffix()
        {
            var now = new DateTime(2026, 3, 1, 2, 3, 4, 5);
            Assert.Equal("Screenshot_20260301_020304_005_1.png",
                OutputNames.UniquePng("", now, value => !value.EndsWith("_1.png", StringComparison.Ordinal)));
            Assert.Equal("shot.v2.png", OutputNames.WithPngExtension("shot.v2"));
            Assert.Equal("shot.PNG", OutputNames.WithPngExtension("shot.PNG"));
        }

        [Fact]
        public void HandlesFractionalDpiAndNegativeCoordinates()
        {
            Assert.Equal(-150, Geometry.ScalePixel(-100, 144));
            Assert.Equal(-100, Geometry.ScaleLogical(-150, 144));
            Assert.Equal(-192, Geometry.AnchorOrigin(-180, 24, 1.5));
            Assert.Equal(-200, Geometry.DragAxis(-180, -300, -200, 0, 2));
        }

        [Fact]
        public void RestoresScreenSelectionClippedToCurrentDesktop()
        {
            var desktop = new Rectangle(-1280, -240, 3200, 1320);
            Assert.Equal(new Rectangle(0, 220, 80, 200),
                Geometry.RestoreSelection(new Rectangle(-1400, -20, 200, 200), desktop));
            Assert.Equal(Rectangle.Empty,
                Geometry.RestoreSelection(new Rectangle(1920, 0, 100, 100), desktop));
        }

        [Fact]
        public void FitsPinScaleWithinBothWindowTrackingLimits() =>
            Assert.Equal(1.1, Geometry.FitScale(new Size(4000, 2000), new Size(5000, 2200)));

        [Fact]
        public void DragIncludesLastDesktopPixelInBothDirectionsAndPreservesWindowClick()
        {
            var bounds = new Size(100, 80);
            var dragSize = new Size(4, 4);
            var start = new Point(10, 20);
            var edge = new Point(99, 79);
            var expected = new Rectangle(10, 20, 90, 60);
            bool dragStarted = false;
            Assert.Equal(expected, Geometry.SelectionFromDrag(start, edge, bounds, false, dragSize, ref dragStarted));
            Assert.Equal(expected, Geometry.SelectionFromDrag(edge, start, bounds, false, dragSize, ref dragStarted));
            Assert.Equal(new Rectangle(40, 20, 60, 60),
                Geometry.SelectionFromDrag(new Point(40, 20), edge, bounds, true, dragSize, ref dragStarted));
            dragStarted = false;
            Assert.Equal(Rectangle.Empty, Geometry.SelectionFromDrag(edge, edge, bounds, false, dragSize, ref dragStarted));
            Assert.Equal(Rectangle.Empty,
                Geometry.SelectionFromDrag(start, new Point(11, 21), bounds, false, dragSize, ref dragStarted));
            Assert.False(dragStarted);
            Assert.Equal(new Rectangle(10, 20, 3, 2),
                Geometry.SelectionFromDrag(start, new Point(12, 21), bounds, false, dragSize, ref dragStarted));
        }

        [Fact]
        public void AreaDragReturningNearOriginRemainsADragWithoutACrop()
        {
            var origin = new Point(10, 20);
            var bounds = new Size(100, 80);
            var dragSize = new Size(4, 4);
            bool dragStarted = false;
            Assert.NotEqual(Rectangle.Empty,
                Geometry.SelectionFromDrag(origin, new Point(50, 60), bounds, false, dragSize, ref dragStarted));
            Assert.Equal(Rectangle.Empty,
                Geometry.SelectionFromDrag(origin, new Point(11, 21), bounds, false, dragSize, ref dragStarted));
            Assert.True(dragStarted);
        }

        [Fact]
        public void DrawingAfterUndoClearsRedo()
        {
            var history = new History<int>();
            history.Push(1);
            history.Push(2);
            history.Undo();
            Assert.Equal(new[] { 1 }, history.Items);
            history.Redo();
            Assert.Equal(new[] { 1, 2 }, history.Items);
            history.Undo();
            history.Push(3);
            Assert.False(history.CanRedo);
            Assert.Equal(new[] { 1, 3 }, history.Items);
        }
    }
}
