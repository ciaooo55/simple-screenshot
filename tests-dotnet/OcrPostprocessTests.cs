using System;
using System.Linq;
using SimpleScreenshot.Core;
using Xunit;

namespace SimpleScreenshot.Tests
{
    public class OcrPostprocessTests
    {
        [Fact]
        public void KeepsRepeatedGlyphSeparatedByBlankAndModelSpace()
        {
            var decoded = OcrPostprocess.Decode(new[] { 0, 1, 1, 0, 1, 3, 3, 2 },
                Enumerable.Repeat(.9f, 8).ToArray(), new[] { "中", "A" });
            Assert.Equal("中中 A", string.Concat(decoded.Select(token => token.Text)));
            Assert.Equal(new[] { 1, 4, 5, 7 }, decoded.Select(token => token.Column));
        }

        [Fact]
        public void JoinsChineseWordsWithoutRemovingLatinSpaces()
        {
            Assert.Equal("你好 test 123 世界", OcrPostprocess.JoinWords(
                new[] { "你", "好", "", "test", "123", "世", "界" }));
        }

        [Fact]
        public void DetectorPreservesADual4KDesktopAndCapsLargerInputs()
        {
            Assert.Equal((7680, 2176), OcrPostprocess.DetectorDimensions(7680, 2160));
            Assert.Equal((1472, 736), OcrPostprocess.DetectorDimensions(400, 200));
            var (width, height) = OcrPostprocess.DetectorDimensions(8192, 8192);
            Assert.Equal((4480, 4480), (width, height));
        }

        [Fact]
        public void DetectionThresholdDilationScoreAndUnclip()
        {
            const int width = 40, height = 28;
            var map = new float[width * height];
            for (int y = 7; y <= 13; y++)
                for (int x = 8; x <= 23; x++) map[y * width + x] = .89f;
            for (int y = 19; y <= 25; y++)
                for (int x = 26; x <= 36; x++) map[y * width + x] = .35f;
            var box = Assert.Single(OcrPostprocess.Detect(map, width, height));
            Assert.True(box[0].X < 8 && box[0].Y < 7);
            Assert.True(box[2].X > 24 && box[2].Y > 14);
            Assert.Empty(OcrPostprocess.Detect(map, width, height, threshold: .99f));
        }

        [Fact]
        public void DetectionMaintainsRotatedContour()
        {
            const int length = 48;
            var map = new float[length * length];
            for (int x = 7; x <= 28; x++)
                for (int y = x / 2 + 8; y < x / 2 + 16; y++) map[y * length + x] = .94f;
            var box = Assert.Single(OcrPostprocess.Detect(map, length, length));
            Assert.True(Math.Abs(box[1].Y - box[0].Y) > 3);
            Assert.True((box[1] - box[0]).Length > (box[3] - box[0]).Length);
        }
    }
}
