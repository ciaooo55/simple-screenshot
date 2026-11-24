using System;
using System.Diagnostics;
using System.IO;
using System.IO.Pipes;
using System.Linq;
using System.Security.Principal;
using System.Threading;
using System.Windows.Forms;

namespace SimpleScreenshot
{
    static class Program
    {
        internal static string DataDirectory { get; } = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "SimpleScreenshot");

        [STAThread]
        static void Main(string[] arguments)
        {
            if (arguments.Length > 1 && arguments[0] == "--ocr-worker")
            {
                OcrClient.Worker(arguments[1], arguments.Contains("--safe-mode"));
                return;
            }
            Log.Install();
            Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Native.SetCurrentProcessExplicitAppUserModelID("SimpleScreenshot.1");

            string id;
            using (var identity = WindowsIdentity.GetCurrent())
                id = "SimpleScreenshot-" + identity.User.Value + "-" + Process.GetCurrentProcess().SessionId;

            try
            {
                using (var mutex = new Mutex(false, @"Local\" + id))
                {
                    bool primary;
                    try { primary = mutex.WaitOne(0); }
                    catch (AbandonedMutexException) { primary = true; }
                    if (!primary)
                    {
                        try
                        {
                            using (var client = new NamedPipeClientStream(".", id, PipeDirection.Out))
                            {
                                client.Connect(700);
                                client.WriteByte(1);
                            }
                        }
                        catch (Exception error) { Log.Write(error); }
                        return;
                    }

                    try
                    {
                        using (var host = new TrayHost(arguments.Contains("--autostart")))
                        using (var server = new InstanceServer(id, host.UsedAgain))
                            Application.Run(host);
                    }
                    finally { mutex.ReleaseMutex(); }
                }
            }
            catch (Exception error)
            {
                Log.Write(error);
                MessageBox.Show("无法启动简易截图工具：" + error.Message, "简易截图工具",
                    MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }
    }

    sealed class InstanceServer : IDisposable
    {
        readonly string name;
        readonly Action activate;
        readonly Thread thread;
        readonly object gate = new object();
        NamedPipeServerStream pipe;
        bool finished;

        internal InstanceServer(string name, Action activate)
        {
            this.name = name;
            this.activate = activate;
            thread = new Thread(Listen) { IsBackground = true, Name = "Single instance IPC" };
            thread.Start();
        }

        void Listen()
        {
            while (true)
            {
                try
                {
                    NamedPipeServerStream server;
                    lock (gate)
                    {
                        if (finished) return;
                        pipe = server = new NamedPipeServerStream(name, PipeDirection.In, 1,
                            PipeTransmissionMode.Byte, PipeOptions.Asynchronous);
                    }
                    using (server)
                    {
                        server.WaitForConnection();
                        if (server.ReadByte() == 1)
                            activate();
                    }
                }
                catch (Exception error)
                {
                    lock (gate) if (finished) return;
                    Log.Write(error);
                    Thread.Sleep(100);
                }
            }
        }

        public void Dispose()
        {
            lock (gate)
            {
                finished = true;
                pipe?.Dispose();
            }
        }
    }

    static class Log
    {
        static readonly object Gate = new object();
        internal static void Install()
        {
            Application.ThreadException += (_, e) => Write(e.Exception);
            AppDomain.CurrentDomain.UnhandledException += (_, e) =>
            {
                Write(e.ExceptionObject);
                if (e.IsTerminating) Write(e.ExceptionObject, "native-crash.log");
            };
        }

        internal static void Write(object message, string file = "app.log")
        {
            lock (Gate)
            {
                try
                {
                    Directory.CreateDirectory(Program.DataDirectory);
                    string path = Path.Combine(Program.DataDirectory, file);
                    if (File.Exists(path) && new FileInfo(path).Length > 2 * 1024 * 1024)
                    {
                        File.Delete(path + ".1");
                        File.Move(path, path + ".1");
                    }
                    File.AppendAllText(path, $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] {message}{Environment.NewLine}");
                }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
            }
        }
    }
}
