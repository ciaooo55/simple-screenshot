using System;
using System.IO;
using System.Linq;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;
using System.Xml;
using System.Xml.Linq;

namespace SimpleScreenshot.Core
{
    [DataContract]
    public sealed class Settings
    {
        public const int CurrentVersion = 3;
        [DataMember(Name = "version")] public int Version { get; set; } = CurrentVersion;
        [DataMember(Name = "copy_hotkey")] public string CopyHotkey { get; set; }
        [DataMember(Name = "save_hotkey")] public string SaveHotkey { get; set; }
        [DataMember(Name = "pin_hotkey")] public string PinHotkey { get; set; }
        [DataMember(Name = "save_directory")] public string SaveDirectory { get; set; }
        [DataMember(Name = "start_with_windows")] public bool StartWithWindows { get; set; }
        [DataMember(Name = "hide_pins_on_capture")] public bool HidePinsOnCapture { get; set; }

        public static Settings Defaults(string programDirectory) => new Settings
        {
            CopyHotkey = "Alt+A", SaveHotkey = "Alt+S", PinHotkey = "Alt+Q",
            SaveDirectory = Path.Combine(programDirectory, "tp")
        };

        public Hotkey[] ParseHotkeys()
        {
            var result = new[] { CopyHotkey, SaveHotkey, PinHotkey }.Select(Hotkey.Parse).ToArray();
            if (result.Distinct().Count() != result.Length)
                throw new ArgumentException("三个快捷键不能相同。");
            return result;
        }
    }

    public sealed class SettingsStore
    {
        [DataContract]
        sealed class Stored
        {
            [DataMember(Name = "version")] public int? Version { get; set; }
            [DataMember(Name = "copy_hotkey")] public string CopyHotkey { get; set; }
            [DataMember(Name = "save_hotkey")] public string SaveHotkey { get; set; }
            [DataMember(Name = "pin_hotkey")] public string PinHotkey { get; set; }
            [DataMember(Name = "save_directory")] public string SaveDirectory { get; set; }
            [DataMember(Name = "start_with_windows")] public bool? StartWithWindows { get; set; }
            [DataMember(Name = "hide_pins_on_capture")] public bool? HidePinsOnCapture { get; set; }
        }

        public string DirectoryPath { get; }
        public string ProgramDirectory { get; }
        public string SettingsPath => Path.Combine(DirectoryPath, "settings.json");
        public string LastWarning { get; private set; }

        public SettingsStore(string directoryPath, string programDirectory)
        {
            DirectoryPath = directoryPath;
            ProgramDirectory = programDirectory;
        }

        public Settings Load()
        {
            LastWarning = null;
            var defaults = Settings.Defaults(ProgramDirectory);
            if (!File.Exists(SettingsPath))
                return defaults;

            try
            {
                Settings settings;
                using (var stream = File.OpenRead(SettingsPath))
                    settings = Decode(stream, defaults);
                return settings;
            }
            catch (Exception ex)
            {
                LastWarning = "设置文件读取失败，已使用默认设置：" + ex.Message;
                try
                {
                    File.AppendAllText(Path.Combine(DirectoryPath, "settings.error.log"),
                        $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] {LastWarning}{Environment.NewLine}");
                }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
                return defaults;
            }
        }

        public static Settings Decode(Stream stream, Settings defaults)
        {
            XElement document;
            using (var reader = JsonReaderWriterFactory.CreateJsonReader(stream, XmlDictionaryReaderQuotas.Max))
                document = XElement.Load(reader);
            if ((string)document.Attribute("type") != "object")
                throw new SerializationException("设置文件根节点不是对象。");
            foreach (var field in document.Elements())
            {
                var name = field.Name.LocalName;
                var kind = (string)field.Attribute("type");
                switch (name)
                {
                    case "version":
                        if (kind != "number") throw new SerializationException("设置版本无效。");
                        break;
                    case "pin_hotkey":
                        if (kind == "null") break;
                        goto case "copy_hotkey";
                    case "copy_hotkey": case "save_hotkey": case "save_directory":
                        if (kind != "string") throw new SerializationException("快捷键或保存目录无效。");
                        break;
                    case "start_with_windows": case "hide_pins_on_capture":
                        if (kind != "boolean") throw new SerializationException("开机启动或贴图设置无效。");
                        break;
                }
            }
            Stored stored;
            using (var reader = document.CreateReader())
                stored = (Stored)new DataContractJsonSerializer(typeof(Stored)).ReadObject(reader);
            int version = stored.Version ?? Settings.CurrentVersion;
            if (version < 1 || version > Settings.CurrentVersion)
                throw new SerializationException("不支持的设置版本：" + version);
            var copy = Hotkey.Parse(stored.CopyHotkey ?? defaults.CopyHotkey);
            var save = Hotkey.Parse(stored.SaveHotkey ?? defaults.SaveHotkey);
            var pin = stored.PinHotkey == null
                ? new[] { "Alt+Q", "Alt+W", "Alt+E", "Alt+X" }.Select(Hotkey.Parse)
                    .First(candidate => !candidate.Equals(copy) && !candidate.Equals(save))
                : Hotkey.Parse(stored.PinHotkey);
            string directory = (stored.SaveDirectory ?? defaults.SaveDirectory).Trim();
            if (string.IsNullOrWhiteSpace(directory))
                throw new SerializationException("保存目录无效。");
            var settings = new Settings
            {
                CopyHotkey = copy.ToString(), SaveHotkey = save.ToString(), PinHotkey = pin.ToString(),
                SaveDirectory = directory, StartWithWindows = stored.StartWithWindows ?? defaults.StartWithWindows,
                HidePinsOnCapture = version == Settings.CurrentVersion &&
                    (stored.HidePinsOnCapture ?? defaults.HidePinsOnCapture)
            };
            settings.ParseHotkeys();
            return settings;
        }

        public void Save(Settings settings)
        {
            Directory.CreateDirectory(DirectoryPath);
            string temporary = SettingsPath + ".tmp";
            try
            {
                using (var stream = File.Create(temporary))
                {
                    new DataContractJsonSerializer(typeof(Settings)).WriteObject(stream, settings);
                    stream.Flush(true);
                }

                if (File.Exists(SettingsPath))
                    File.Replace(temporary, SettingsPath, null);
                else
                    File.Move(temporary, SettingsPath);
            }
            finally
            {
                File.Delete(temporary);
            }
        }
    }
}
