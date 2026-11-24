using System;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.IO.Pipes;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Win32.SafeHandles;
using Timer = System.Threading.Timer;

namespace SimpleScreenshot
{
    sealed class OcrClient : IDisposable
    {
        const int MaxPayload = 384 * 1024 * 1024;
        const int MaxSpans = 500000;
        static readonly string Executable = typeof(OcrClient).Assembly.Location;
        static readonly string OcrDirectory = Path.Combine(Path.GetDirectoryName(Executable), "ocr");
        readonly object gate = new object();
        readonly Timer idle;
        NamedPipeServerStream server;
        Process worker;
        bool busy, disposed;
        bool safeMode = Environment.GetEnvironmentVariable("SIMPLESCREENSHOT_OCR_SAFE_MODE") == "1";

        internal OcrClient() => idle = new Timer(_ => ReleaseIdle(), null, Timeout.Infinite, Timeout.Infinite);

        internal async Task<Tuple<string, RectangleF>[]> Recognize(Bitmap image)
        {
            Bitmap copy;
            lock (gate)
            {
                if (disposed) throw new ObjectDisposedException(nameof(OcrClient));
                if (busy) throw new InvalidOperationException("已有文字识别任务，请稍后再试。");
                copy = new Bitmap(image);
                busy = true;
                idle.Change(Timeout.Infinite, Timeout.Infinite);
            }
            try { return await Task.Run(() => Send(copy)).ConfigureAwait(false); }
            finally
            {
                copy.Dispose();
                lock (gate)
                {
                    busy = false;
                    if (!disposed) idle.Change(TimeSpan.FromMinutes(5), Timeout.InfiniteTimeSpan);
                }
            }
        }

        Tuple<string, RectangleF>[] Send(Bitmap image)
        {
            using (var payload = new MemoryStream())
            {
                image.Save(payload, ImageFormat.Bmp);
                if (payload.Length > MaxPayload) throw new ArgumentException("截图过大，请缩小选区后重试。");
                NamedPipeServerStream connection;
                int? expectedClientPid = null;
                lock (gate)
                {
                    if (disposed) throw new ObjectDisposedException(nameof(OcrClient));
                    if (worker == null || worker.HasExited)
                    {
                        StopWorker();
                        if (!File.Exists(Path.Combine(OcrDirectory, "SimpleScreenshot.Ocr.dll")))
                            throw new InvalidOperationException("未找到文字识别组件，请完整解压包含 ocr 文件夹的压缩包。");
                        string name = "SimpleScreenshot-OCR-" + Guid.NewGuid().ToString("N");
                        var security = new PipeSecurity();
                        security.SetAccessRuleProtection(true, false);
                        using (var identity = WindowsIdentity.GetCurrent())
                            security.AddAccessRule(new PipeAccessRule(identity.User, PipeAccessRights.FullControl,
                                AccessControlType.Allow));
                        server = new NamedPipeServerStream(name, PipeDirection.InOut, 1, PipeTransmissionMode.Byte,
                            PipeOptions.Asynchronous, 0, 0, security);
                        try
                        {
                            worker = Process.Start(new ProcessStartInfo
                            {
                                FileName = Executable,
                                Arguments = "--ocr-worker " + name + (safeMode ? " --safe-mode" : ""),
                                UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = OcrDirectory
                            });
                            expectedClientPid = worker.Id;
                        }
                        catch { StopWorker(); throw; }
                    }
                    connection = server;
                }
                bool authenticated = !expectedClientPid.HasValue;
                try
                {
                    if (expectedClientPid.HasValue)
                    {
                        using (var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(15)))
                            connection.WaitForConnectionAsync(timeout.Token).GetAwaiter().GetResult();
                        if (!GetNamedPipeClientProcessId(connection.SafePipeHandle, out uint actualClientPid) ||
                            actualClientPid != (uint)expectedClientPid.Value)
                            throw new IOException("无法验证文字识别进程的连接。");
                        authenticated = true;
                    }
                    using (var output = new BinaryWriter(connection, System.Text.Encoding.UTF8, true))
                    using (var input = new BinaryReader(connection, System.Text.Encoding.UTF8, true))
                    {
                        output.Write((int)payload.Length);
                        output.Write(payload.GetBuffer(), 0, (int)payload.Length);
                        output.Flush();
                        int count = input.ReadInt32();
                        if (count == -1) throw new OcrFailedException(input.ReadString());
                        if (count < 0 || count > MaxSpans) throw new IOException();
                        var response = new Tuple<string, RectangleF>[count];
                        for (var i = 0; i < count; i++)
                            response[i] = Tuple.Create(input.ReadString(),
                                new RectangleF(input.ReadSingle(), input.ReadSingle(), input.ReadSingle(), input.ReadSingle()));
                        return response;
                    }
                }
                catch (OcrFailedException) { throw; }
                catch (Exception error)
                {
                    lock (gate)
                    {
                        if (authenticated) safeMode = true;
                        if (worker != null && worker.HasExited)
                            Log.Write($"文字识别进程退出：0x{worker.ExitCode:X8}", "native-crash.log");
                        StopWorker();
                    }
                    if (authenticated)
                    {
                        Log.Write(error, "native-crash.log");
                        throw new InvalidOperationException("识别进程异常退出，已启用系统 OCR 兼容模式，请重试。", error);
                    }
                    Log.Write(error);
                    throw new InvalidOperationException(error is OperationCanceledException
                        ? "文字识别进程连接超时，请重试。"
                        : "无法连接文字识别进程，请重试。", error);
                }
            }
        }

        sealed class OcrFailedException : Exception
        {
            internal OcrFailedException(string message) : base(message) { }
        }

        static Tuple<string, RectangleF>[] Invoke(Bitmap image, bool safe)
        {
            SetDllDirectory(OcrDirectory);
            var assembly = Assembly.LoadFrom(Path.Combine(OcrDirectory, "SimpleScreenshot.Ocr.dll"));
            var method = assembly.GetType("SimpleScreenshot.Ocr.Engine", true).GetMethod("Recognize");
            return (Tuple<string, RectangleF>[])method.Invoke(null, new object[] { image, OcrDirectory, safe });
        }

        [DllImport("kernel32", CharSet = CharSet.Unicode)]
        static extern bool SetDllDirectory(string path);

        [DllImport("kernel32", ExactSpelling = true)]
        static extern bool GetNamedPipeClientProcessId(SafePipeHandle pipe, out uint processId);

        internal static void Worker(string name, bool safe)
        {
            try
            {
                using (var pipe = new NamedPipeClientStream(".", name, PipeDirection.InOut))
                {
                    pipe.Connect(10000);
                    using (var input = new BinaryReader(pipe, System.Text.Encoding.UTF8, true))
                    using (var output = new BinaryWriter(pipe, System.Text.Encoding.UTF8, true))
                    {
                        while (true)
                        {
                            int length;
                            try { length = input.ReadInt32(); } catch (EndOfStreamException) { return; }
                            if (length <= 0 || length > MaxPayload) return;
                            byte[] encoded = input.ReadBytes(length);
                            if (encoded.Length != length) return;
                            Tuple<string, RectangleF>[] results;
                            try
                            {
                                using (var data = new MemoryStream(encoded))
                                using (var image = new Bitmap(data))
                                    results = Invoke(image, safe);
                            }
                            catch (Exception error)
                            {
                                var reason = error is TargetInvocationException && error.InnerException != null ? error.InnerException : error;
                                Log.Write(reason);
                                output.Write(-1);
                                output.Write(reason.Message);
                                output.Flush();
                                continue;
                            }
                            output.Write(results.Length);
                            foreach (var result in results)
                            {
                                output.Write(result.Item1);
                                output.Write(result.Item2.X);
                                output.Write(result.Item2.Y);
                                output.Write(result.Item2.Width);
                                output.Write(result.Item2.Height);
                            }
                            output.Flush();
                        }
                    }
                }
            }
            catch (Exception error) { Log.Write(error); }
        }

        void ReleaseIdle()
        {
            lock (gate) if (!busy) StopWorker();
        }

        void StopWorker()
        {
            server?.Dispose();
            server = null;
            if (worker == null) return;
            try { if (!worker.HasExited) worker.Kill(); }
            catch (InvalidOperationException) { }
            worker.Dispose();
            worker = null;
        }

        public void Dispose()
        {
            lock (gate)
            {
                disposed = true;
                idle.Dispose();
                StopWorker();
            }
        }
    }
}
