#include <juce_audio_formats/juce_audio_formats.h>
#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_audio_utils/juce_audio_utils.h>
#include <juce_gui_extra/juce_gui_extra.h>

#include <cstring>
#include <optional>

static juce::String u8str(const char* s)
{
    return juce::String::fromUTF8(s);
}

namespace vsthost
{
class PluginHost
{
public:
    PluginHost()
    {
        formatManager.addDefaultFormats();
    }

    bool loadPluginFromFile(const juce::File& pluginFile, double sampleRate, int blockSize, juce::String& error)
    {
        unloadPlugin();

        juce::OwnedArray<juce::PluginDescription> types;
        for (auto* format : formatManager.getFormats())
        {
            format->findAllTypesForFile(types, pluginFile.getFullPathName());
            if (!types.isEmpty())
                break;
        }

        if (types.isEmpty())
        {
            error = u8str(u8"\u6ca1\u6709\u8bc6\u522b\u5230\u53ef\u52a0\u8f7d\u7684\u63d2\u4ef6\u7c7b\u578b\uff08\u4ec5\u652f\u6301\u5df2\u542f\u7528\u7684\u683c\u5f0f\uff0c\u5982 VST3\uff09");
            return false;
        }

        pluginDescription = *types.getFirst();

        std::unique_ptr<juce::AudioPluginInstance> instance(
            formatManager.createPluginInstance(pluginDescription, sampleRate, blockSize, error));

        if (instance == nullptr)
            return false;

        pluginInstance = std::move(instance);
        return true;
    }

    void unloadPlugin()
    {
        if (pluginInstance != nullptr)
            pluginInstance->releaseResources();

        pluginInstance.reset();
        pluginDescription = {};
    }

    juce::AudioPluginInstance* get() const { return pluginInstance.get(); }
    const juce::PluginDescription& getDescription() const { return pluginDescription; }

private:
    juce::AudioPluginFormatManager formatManager;
    juce::PluginDescription pluginDescription;
    std::unique_ptr<juce::AudioPluginInstance> pluginInstance;
};

class OfflineProcessor
{
public:
    explicit OfflineProcessor(PluginHost& hostToUse) : host(hostToUse) {}

    struct ProcessStats
    {
        double inputRmsDb = 0.0;
        double diffRmsDb = 0.0;
        float maxAbsDiff = 0.0f;
        int outputChannels = 0;
    };

    bool processAudioFileToFile(const juce::File& inputFile,
                                const juce::File& outputWavFile,
                                juce::String& error,
                                ProcessStats* stats = nullptr)
    {
        auto* plugin = host.get();
        if (plugin == nullptr)
        {
            error = u8str(u8"\u672a\u52a0\u8f7d\u63d2\u4ef6");
            return false;
        }

        juce::AudioFormatManager formatManager;
        formatManager.registerBasicFormats();

        std::unique_ptr<juce::AudioFormatReader> reader(formatManager.createReaderFor(inputFile));
        if (reader == nullptr)
        {
            error = u8str(u8"\u65e0\u6cd5\u8bfb\u53d6\u8f93\u5165\u97f3\u9891\u6587\u4ef6");
            return false;
        }

        const auto sampleRate = reader->sampleRate;
        const auto numSamples64 = reader->lengthInSamples;
        const int numInputChannels = static_cast<int>(reader->numChannels);

        const int desiredBlockSize = juce::jlimit(64, 8192, lastBlockSize);

        const int numPluginIns = juce::jmax(1, plugin->getTotalNumInputChannels());
        const int numPluginOuts = juce::jmax(1, plugin->getTotalNumOutputChannels());

        int processChannels = numInputChannels;

        if (numInputChannels == 1 && numPluginOuts >= 2)
            processChannels = 2;

        if (stats != nullptr)
            stats->outputChannels = processChannels;

        plugin->setNonRealtime(true);
        plugin->setPlayConfigDetails(processChannels, processChannels, sampleRate, desiredBlockSize);
        plugin->prepareToPlay(sampleRate, desiredBlockSize);
        plugin->reset();
        plugin->suspendProcessing(false);

        const int bufferChannels = juce::jmax(processChannels, juce::jmax(numPluginIns, numPluginOuts));

        juce::WavAudioFormat wav;
        outputWavFile.getParentDirectory().createDirectory();
        juce::TemporaryFile tempFile(outputWavFile);

        std::unique_ptr<juce::FileOutputStream> outputStream(tempFile.getFile().createOutputStream());
        if (outputStream == nullptr || !outputStream->openedOk())
        {
            error = u8str(u8"\u65e0\u6cd5\u521b\u5efa\u8f93\u51fa\u6587\u4ef6\u6d41");
            plugin->releaseResources();
            return false;
        }

        std::unique_ptr<juce::AudioFormatWriter> writer(wav.createWriterFor(outputStream.get(),
                                                                            sampleRate,
                                                                            static_cast<unsigned int>(processChannels),
                                                                            24,
                                                                            {},
                                                                            0));
        if (writer == nullptr)
        {
            error = u8str(u8"\u65e0\u6cd5\u521b\u5efa WAV \u5199\u5165\u5668");
            plugin->releaseResources();
            return false;
        }
        outputStream.release();

        juce::AudioBuffer<float> buffer(bufferChannels, desiredBlockSize);
        juce::AudioBuffer<float> dry(processChannels, desiredBlockSize);
        juce::MidiBuffer midi;

        double drySumSquares = 0.0;
        double diffSumSquares = 0.0;
        float maxAbsDiff = 0.0f;
        int64_t totalSamples = 0;

        int64_t position = 0;
        while (position < numSamples64)
        {
            const int numThisTime = static_cast<int>(juce::jmin<int64_t>(desiredBlockSize, numSamples64 - position));

            buffer.clear();
            reader->read(&buffer, 0, numThisTime, position, true, true);

            if (numInputChannels == 1 && processChannels == 2)
                buffer.copyFrom(1, 0, buffer, 0, 0, numThisTime);

            for (int ch = 0; ch < processChannels; ++ch)
                dry.copyFrom(ch, 0, buffer, ch, 0, numThisTime);

            plugin->processBlock(buffer, midi);

            for (int ch = 0; ch < processChannels; ++ch)
            {
                const auto* dryPtr = dry.getReadPointer(ch);
                const auto* wetPtr = buffer.getReadPointer(ch);
                for (int i = 0; i < numThisTime; ++i)
                {
                    const float d = dryPtr[i];
                    const float w = wetPtr[i];
                    const float diff = w - d;
                    drySumSquares += static_cast<double>(d) * static_cast<double>(d);
                    diffSumSquares += static_cast<double>(diff) * static_cast<double>(diff);
                    maxAbsDiff = juce::jmax(maxAbsDiff, std::abs(diff));
                }
            }
            totalSamples += static_cast<int64_t>(processChannels) * static_cast<int64_t>(numThisTime);

            if (!writer->writeFromAudioSampleBuffer(buffer, 0, numThisTime))
            {
                error = u8str(u8"\u5199\u5165\u8f93\u51fa\u6587\u4ef6\u5931\u8d25");
                plugin->releaseResources();
                plugin->setNonRealtime(false);
                return false;
            }

            position += numThisTime;
        }

        writer.reset();
        if (!tempFile.overwriteTargetFileWithTemporary())
        {
            error = u8str(u8"\u65e0\u6cd5\u8986\u76d6\u5199\u5165\u8f93\u51fa\u6587\u4ef6");
            plugin->releaseResources();
            plugin->setNonRealtime(false);
            return false;
        }

        plugin->releaseResources();
        plugin->setNonRealtime(false);

        if (stats != nullptr && totalSamples > 0)
        {
            const double dryRms = std::sqrt(drySumSquares / static_cast<double>(totalSamples));
            const double diffRms = std::sqrt(diffSumSquares / static_cast<double>(totalSamples));
            stats->inputRmsDb = juce::Decibels::gainToDecibels(dryRms, -300.0);
            stats->diffRmsDb = juce::Decibels::gainToDecibels(diffRms, -300.0);
            stats->maxAbsDiff = maxAbsDiff;
        }
        return true;
    }

    std::vector<float> processInterleavedFloatArray(const float* inputInterleaved,
                                                    int numChannels,
                                                    int numSamples,
                                                    double sampleRate,
                                                    juce::String& error) const
    {
        std::vector<float> output(static_cast<size_t>(numSamples), 0.0f);

        auto* plugin = host.get();
        if (plugin == nullptr)
        {
            error = u8str(u8"\u672a\u52a0\u8f7d\u63d2\u4ef6");
            return output;
        }

        if (inputInterleaved == nullptr || numChannels <= 0 || numSamples <= 0 || sampleRate <= 0.0)
        {
            error = u8str(u8"\u6570\u7ec4\u8f93\u5165\u53c2\u6570\u65e0\u6548");
            return output;
        }

        const int desiredBlockSize = juce::jlimit(64, 8192, lastBlockSize);
        const int numPluginIns = juce::jmax(1, plugin->getTotalNumInputChannels());
        const int numPluginOuts = juce::jmax(1, plugin->getTotalNumOutputChannels());

        int processChannels = numChannels;
        if (numChannels == 1 && numPluginOuts >= 2)
            processChannels = 2;
        
        plugin->setNonRealtime(true);
        plugin->setPlayConfigDetails(processChannels, processChannels, sampleRate, desiredBlockSize);
        plugin->prepareToPlay(sampleRate, desiredBlockSize);
        plugin->reset();
        plugin->suspendProcessing(false);

        const int bufferChannels = juce::jmax(processChannels, juce::jmax(numPluginIns, numPluginOuts));

        juce::AudioBuffer<float> buffer(bufferChannels, desiredBlockSize);
        juce::MidiBuffer midi;

        int position = 0;
        while (position < numSamples)
        {
            const int numThisTime = juce::jmin(desiredBlockSize, numSamples - position);
            buffer.clear();

            for (int ch = 0; ch < numChannels; ++ch)
            {
                auto* dst = buffer.getWritePointer(ch);
                const float* src = inputInterleaved + static_cast<size_t>(position) * static_cast<size_t>(numChannels) + static_cast<size_t>(ch);
                for (int i = 0; i < numThisTime; ++i)
                    dst[i] = src[static_cast<size_t>(i) * static_cast<size_t>(numChannels)];
            }
            
            if (numChannels == 1 && processChannels == 2)
                buffer.copyFrom(1, 0, buffer, 0, 0, numThisTime);

            plugin->processBlock(buffer, midi);

            float* outDst = output.data() + position;
            
            if (processChannels == 1)
            {
                const auto* src = buffer.getReadPointer(0);
                for (int i = 0; i < numThisTime; ++i)
                    outDst[i] = src[i];
            }
            else
            {
                const float scale = 1.0f / static_cast<float>(processChannels);
                
                const auto* src0 = buffer.getReadPointer(0);
                for (int i = 0; i < numThisTime; ++i)
                    outDst[i] = src0[i];

                for (int ch = 1; ch < processChannels; ++ch)
                {
                    const auto* src = buffer.getReadPointer(ch);
                    for (int i = 0; i < numThisTime; ++i)
                        outDst[i] += src[i];
                }

                for (int i = 0; i < numThisTime; ++i)
                    outDst[i] *= scale;
            }

            position += numThisTime;
        }

        plugin->releaseResources();
        plugin->setNonRealtime(false);
        return output;
    }

    std::vector<float> processMonoFloatArray(const float* inputMono, int numSamples, double sampleRate, juce::String& error) const
    {
        return processInterleavedFloatArray(inputMono, 1, numSamples, sampleRate, error);
    }

    std::vector<float> processMonoFloatArray(const float* inputMono, int numSamples, juce::String& error) const
    {
        return processMonoFloatArray(inputMono, numSamples, 44100.0, error);
    }

    void setBlockSize(int newBlockSize) { lastBlockSize = newBlockSize; }

private:
    PluginHost& host;
    int lastBlockSize = 1024;
};

class ProcessorThread : public juce::ThreadWithProgressWindow
{
public:
    ProcessorThread(OfflineProcessor& processorToUse, juce::File in, juce::File out)
        : juce::ThreadWithProgressWindow(u8str(u8"\u5904\u7406\u4e2d\u2026"), true, true),
          processor(processorToUse),
          inputFile(std::move(in)),
          outputFile(std::move(out))
    {
    }

    void run() override
    {
        setProgress(-1.0);
        ok = processor.processAudioFileToFile(inputFile, outputFile, error, &stats);
    }

    bool ok = false;
    juce::String error;
    OfflineProcessor::ProcessStats stats;

private:
    OfflineProcessor& processor;
    juce::File inputFile;
    juce::File outputFile;
};

static std::vector<float> parseFloatList(const juce::String& text, juce::String& error)
{
    std::vector<float> values;
    error.clear();

    juce::String s = text;
    s = s.replaceCharacters(",;\t\r\n", "     ");
    s = s.trim();

    if (s.isEmpty())
        return values;

    juce::StringArray tokens;
    tokens.addTokens(s, " ", "");
    tokens.removeEmptyStrings();

    values.reserve(static_cast<size_t>(tokens.size()));
    for (auto& tok : tokens)
    {
        const auto t = tok.trim();
        if (t.isEmpty())
            continue;

        if (!t.containsOnly("+-0123456789.eE"))
        {
            error = u8str(u8"\u8f93\u5165\u6570\u7ec4\u4e2d\u5305\u542b\u975e\u6570\u503c\u5185\u5bb9");
            values.clear();
            return values;
        }

        values.push_back(static_cast<float>(t.getDoubleValue()));
    }

    return values;
}

static juce::String formatFloatList(const std::vector<float>& values)
{
    juce::String out;
    for (size_t i = 0; i < values.size(); ++i)
    {
        out << juce::String(values[i], 7);
        if (i + 1 < values.size())
            out << ",\n";
    }
    return out;
}

class ArrayProcessComponent final : public juce::Component
{
public:
    explicit ArrayProcessComponent(vsthost::OfflineProcessor& processorToUse)
        : processor(processorToUse)
    {
        addAndMakeVisible(sampleRateLabel);
        sampleRateLabel.setText(u8str(u8"\u91c7\u6837\u7387"), juce::dontSendNotification);

        addAndMakeVisible(sampleRateEditor);
        sampleRateEditor.setText("44100", juce::dontSendNotification);
        sampleRateEditor.setInputRestrictions(10, "0123456789.");

        addAndMakeVisible(inputLabel);
        inputLabel.setText(u8str(u8"\u8f93\u5165\u6570\u7ec4\uff08\u5355\u58f0\u9053 float\uff0c\u652f\u6301\u7a7a\u683c/\u6362\u884c/\u9017\u53f7\u5206\u9694\uff09"), juce::dontSendNotification);

        addAndMakeVisible(inputEditor);
        inputEditor.setMultiLine(true);
        inputEditor.setReturnKeyStartsNewLine(true);
        inputEditor.setScrollbarsShown(true);

        addAndMakeVisible(outputLabel);
        outputLabel.setText(u8str(u8"\u8f93\u51fa\u6570\u7ec4\uff08\u5355\u58f0\u9053 float\uff09"), juce::dontSendNotification);

        addAndMakeVisible(outputEditor);
        outputEditor.setMultiLine(true);
        outputEditor.setReturnKeyStartsNewLine(true);
        outputEditor.setScrollbarsShown(true);
        outputEditor.setReadOnly(true);

        addAndMakeVisible(processButton);
        processButton.setButtonText(u8str(u8"\u5904\u7406"));
        processButton.onClick = [this] { process(); };

        addAndMakeVisible(copyButton);
        copyButton.setButtonText(u8str(u8"\u590d\u5236\u8f93\u51fa"));
        copyButton.onClick = [this]
        {
            juce::SystemClipboard::copyTextToClipboard(outputEditor.getText());
        };

        addAndMakeVisible(clearButton);
        clearButton.setButtonText(u8str(u8"\u6e05\u7a7a"));
        clearButton.onClick = [this]
        {
            inputEditor.clear();
            outputEditor.clear();
        };
    }

    void resized() override
    {
        auto area = getLocalBounds().reduced(12);
        auto top = area.removeFromTop(28);
        sampleRateLabel.setBounds(top.removeFromLeft(60));
        top.removeFromLeft(6);
        sampleRateEditor.setBounds(top.removeFromLeft(100));
        top.removeFromLeft(10);
        processButton.setBounds(top.removeFromLeft(100));
        top.removeFromLeft(8);
        copyButton.setBounds(top.removeFromLeft(140));
        top.removeFromLeft(8);
        clearButton.setBounds(top.removeFromLeft(100));

        area.removeFromTop(10);
        inputLabel.setBounds(area.removeFromTop(20));
        area.removeFromTop(6);
        inputEditor.setBounds(area.removeFromTop(area.getHeight() / 2 - 18));

        area.removeFromTop(10);
        outputLabel.setBounds(area.removeFromTop(20));
        area.removeFromTop(6);
        outputEditor.setBounds(area);
    }

private:
    void process()
    {
        const double sr = sampleRateEditor.getText().getDoubleValue();
        const double sampleRate = sr > 0.0 ? sr : 44100.0;

        juce::String parseError;
        auto input = parseFloatList(inputEditor.getText(), parseError);
        if (parseError.isNotEmpty())
        {
            juce::AlertWindow::showMessageBoxAsync(juce::AlertWindow::WarningIcon, u8str(u8"\u89e3\u6790\u5931\u8d25"), parseError);
            return;
        }

        if (input.empty())
        {
            juce::AlertWindow::showMessageBoxAsync(juce::AlertWindow::InfoIcon, u8str(u8"\u63d0\u793a"), u8str(u8"\u8bf7\u8f93\u5165\u81f3\u5c11\u4e00\u4e2a float"));
            return;
        }

        juce::String error;
        auto out = processor.processMonoFloatArray(input.data(), static_cast<int>(input.size()), sampleRate, error);
        if (error.isNotEmpty())
        {
            juce::AlertWindow::showMessageBoxAsync(juce::AlertWindow::WarningIcon, u8str(u8"\u5904\u7406\u5931\u8d25"), error);
            return;
        }

        outputEditor.setText(formatFloatList(out), juce::dontSendNotification);
    }

    vsthost::OfflineProcessor& processor;
    juce::Label sampleRateLabel;
    juce::TextEditor sampleRateEditor;

    juce::Label inputLabel;
    juce::TextEditor inputEditor;
    juce::Label outputLabel;
    juce::TextEditor outputEditor;

    juce::TextButton processButton;
    juce::TextButton copyButton;
    juce::TextButton clearButton;
};

class ArrayProcessWindow final : public juce::DocumentWindow
{
public:
    explicit ArrayProcessWindow(vsthost::OfflineProcessor& processor)
        : juce::DocumentWindow(u8str(u8"\u6570\u7ec4\u5904\u7406"),
                               juce::Colours::darkgrey,
                               juce::DocumentWindow::closeButton)
    {
        setUsingNativeTitleBar(true);
        setResizable(true, true);
        setContentOwned(new ArrayProcessComponent(processor), true);
        centreWithSize(800, 700);
        setVisible(true);
    }

    void closeButtonPressed() override { setVisible(false); }
};

class MainComponent final : public juce::Component
{
public:
    MainComponent()
        : processor(pluginHost)
    {
        addAndMakeVisible(pluginLabel);
        pluginLabel.setText(u8str(u8"\u63d2\u4ef6\uff1a\u672a\u52a0\u8f7d"), juce::dontSendNotification);

        addAndMakeVisible(inputLabel);
        inputLabel.setText(u8str(u8"\u8f93\u5165\uff1a\u672a\u9009\u62e9"), juce::dontSendNotification);

        addAndMakeVisible(outputLabel);
        outputLabel.setText(u8str(u8"\u8f93\u51fa\uff1a\u672a\u9009\u62e9"), juce::dontSendNotification);

        addAndMakeVisible(blockSizeLabel);
        blockSizeLabel.setText("BlockSize", juce::dontSendNotification);

        addAndMakeVisible(blockSizeEditor);
        blockSizeEditor.setText("1024", juce::dontSendNotification);
        blockSizeEditor.setInputRestrictions(5, "0123456789");

        addAndMakeVisible(loadPluginButton);
        loadPluginButton.setButtonText(u8str(u8"\u9009\u62e9\u63d2\u4ef6\u6587\u4ef6\u2026"));
        loadPluginButton.onClick = [this] { choosePlugin(); };

        addAndMakeVisible(openEditorButton);
        openEditorButton.setButtonText(u8str(u8"\u6253\u5f00\u63d2\u4ef6\u754c\u9762"));
        openEditorButton.onClick = [this] { openPluginEditor(); };

        addAndMakeVisible(inputButton);
        inputButton.setButtonText(u8str(u8"\u9009\u62e9\u8f93\u5165\u97f3\u9891\u2026"));
        inputButton.onClick = [this] { chooseInputAudio(); };

        addAndMakeVisible(outputButton);
        outputButton.setButtonText(u8str(u8"\u9009\u62e9\u8f93\u51fa WAV\u2026"));
        outputButton.onClick = [this] { chooseOutputAudio(); };

        addAndMakeVisible(processButton);
        processButton.setButtonText(u8str(u8"\u5f00\u59cb\u5904\u7406"));
        processButton.onClick = [this] { startProcess(); };

        addAndMakeVisible(arrayProcessButton);
        arrayProcessButton.setButtonText(u8str(u8"\u6570\u7ec4\u5904\u7406\u2026"));
        arrayProcessButton.onClick = [this] { openArrayProcessWindow(); };
        setSize(720, 220);
    }

    void resized() override
    {
        auto area = getLocalBounds().reduced(12);
        auto row = area.removeFromTop(28);
        pluginLabel.setBounds(row);
        area.removeFromTop(6);

        row = area.removeFromTop(28);
        inputLabel.setBounds(row);
        area.removeFromTop(6);

        row = area.removeFromTop(28);
        outputLabel.setBounds(row);
        area.removeFromTop(10);

        row = area.removeFromTop(32);
        loadPluginButton.setBounds(row.removeFromLeft(180));
        row.removeFromLeft(8);
        openEditorButton.setBounds(row.removeFromLeft(160));
        row.removeFromLeft(16);
        blockSizeLabel.setBounds(row.removeFromLeft(70));
        row.removeFromLeft(6);
        blockSizeEditor.setBounds(row.removeFromLeft(80));

        area.removeFromTop(10);
        row = area.removeFromTop(32);
        inputButton.setBounds(row.removeFromLeft(180));
        row.removeFromLeft(8);
        outputButton.setBounds(row.removeFromLeft(180));
        row.removeFromLeft(8);
        processButton.setBounds(row.removeFromLeft(140));
        row.removeFromLeft(8);
        arrayProcessButton.setBounds(row.removeFromLeft(140));
    }

private:
    void openArrayProcessWindow()
    {
        auto* plugin = pluginHost.get();
        if (plugin == nullptr)
        {
            juce::AlertWindow::showMessageBoxAsync(juce::AlertWindow::InfoIcon,
                                                   u8str(u8"\u63d0\u793a"),
                                                   u8str(u8"\u8bf7\u5148\u52a0\u8f7d\u63d2\u4ef6"));
            return;
        }

        arrayWindow.reset();
        arrayWindow = std::make_unique<ArrayProcessWindow>(processor);
    }

    void choosePlugin()
    {
        juce::FileChooser chooser(u8str(u8"\u9009\u62e9\u63d2\u4ef6\u6587\u4ef6\uff08VST3\uff09"), {}, "*.vst3");
        if (!chooser.browseForFileToOpen())
            return;

        const auto file = chooser.getResult();
        auto blockSize = juce::jmax(64, blockSizeEditor.getText().getIntValue());
        processor.setBlockSize(blockSize);

        juce::String error;
        if (!pluginHost.loadPluginFromFile(file, 44100.0, blockSize, error))
        {
            juce::AlertWindow::showMessageBoxAsync(juce::AlertWindow::WarningIcon, u8str(u8"\u52a0\u8f7d\u5931\u8d25"), error);
            pluginLabel.setText(u8str(u8"\u63d2\u4ef6\uff1a\u672a\u52a0\u8f7d"), juce::dontSendNotification);
            return;
        }

        pluginLabel.setText(u8str(u8"\u63d2\u4ef6\uff1a") + pluginHost.getDescription().name, juce::dontSendNotification);
    }

    void openPluginEditor()
    {
        auto* plugin = pluginHost.get();
        if (plugin == nullptr)
        {
            juce::AlertWindow::showMessageBoxAsync(juce::AlertWindow::InfoIcon,
                                                   u8str(u8"\u63d0\u793a"),
                                                   u8str(u8"\u8bf7\u5148\u52a0\u8f7d\u63d2\u4ef6"));
            return;
        }

        if (!plugin->hasEditor())
        {
            juce::AlertWindow::showMessageBoxAsync(juce::AlertWindow::InfoIcon,
                                                   u8str(u8"\u63d0\u793a"),
                                                   u8str(u8"\u8be5\u63d2\u4ef6\u6ca1\u6709\u754c\u9762"));
            return;
        }

        editorWindow.reset();
        editorWindow = std::make_unique<PluginEditorWindow>(*plugin);
    }

    void chooseInputAudio()
    {
        juce::FileChooser chooser(u8str(u8"\u9009\u62e9\u8f93\u5165\u97f3\u9891\u6587\u4ef6"), {}, "*.wav;*.aiff;*.aif;*.flac;*.mp3");
        if (!chooser.browseForFileToOpen())
            return;

        inputFile = chooser.getResult();
        inputLabel.setText(u8str(u8"\u8f93\u5165\uff1a") + inputFile.getFullPathName(), juce::dontSendNotification);
    }

    void chooseOutputAudio()
    {
        juce::FileChooser chooser(u8str(u8"\u9009\u62e9\u8f93\u51fa WAV \u6587\u4ef6"), {}, "*.wav");
        if (!chooser.browseForFileToSave(true))
            return;

        outputFile = chooser.getResult().withFileExtension("wav");
        outputLabel.setText(u8str(u8"\u8f93\u51fa\uff1a") + outputFile.getFullPathName(), juce::dontSendNotification);
    }

    void startProcess()
    {
        auto* plugin = pluginHost.get();
        if (plugin == nullptr)
        {
            juce::AlertWindow::showMessageBoxAsync(juce::AlertWindow::InfoIcon,
                                                   u8str(u8"\u63d0\u793a"),
                                                   u8str(u8"\u8bf7\u5148\u52a0\u8f7d\u63d2\u4ef6"));
            return;
        }

        if (!inputFile.existsAsFile())
        {
            juce::AlertWindow::showMessageBoxAsync(juce::AlertWindow::InfoIcon,
                                                   u8str(u8"\u63d0\u793a"),
                                                   u8str(u8"\u8bf7\u5148\u9009\u62e9\u8f93\u5165\u97f3\u9891"));
            return;
        }

        if (outputFile.getFullPathName().isEmpty())
        {
            juce::AlertWindow::showMessageBoxAsync(juce::AlertWindow::InfoIcon,
                                                   u8str(u8"\u63d0\u793a"),
                                                   u8str(u8"\u8bf7\u5148\u9009\u62e9\u8f93\u51fa\u8def\u5f84"));
            return;
        }

        const auto blockSize = juce::jmax(64, blockSizeEditor.getText().getIntValue());
        processor.setBlockSize(blockSize);

        ProcessorThread thread(processor, inputFile, outputFile);
        thread.runThread();

        if (!thread.ok)
        {
            juce::AlertWindow::showMessageBoxAsync(juce::AlertWindow::WarningIcon, u8str(u8"\u5904\u7406\u5931\u8d25"), thread.error);
            return;
        }

        juce::String statsText;
        statsText << u8str(u8"\u8f93\u51fa\u901a\u9053\u6570\uff1a") << juce::String(thread.stats.outputChannels) << "\n"
                  << u8str(u8"\u8f93\u5165 RMS (dB)\uff1a") << juce::String(thread.stats.inputRmsDb, 2) << "\n"
                  << u8str(u8"\u5dee\u5f02 RMS (dB)\uff1a") << juce::String(thread.stats.diffRmsDb, 2) << "\n"
                  << u8str(u8"\u6700\u5927\u5dee\u5f02\uff1a") << juce::String(thread.stats.maxAbsDiff, 6);

        juce::AlertWindow::showMessageBoxAsync(juce::AlertWindow::InfoIcon,
                                               u8str(u8"\u5b8c\u6210"),
                                               u8str(u8"\u8f93\u51fa\u6587\u4ef6\u5df2\u751f\u6210\uff1a\n") + outputFile.getFullPathName() + "\n\n" + statsText);
    }

    class PluginEditorWindow final : public juce::DocumentWindow
    {
    public:
        explicit PluginEditorWindow(juce::AudioPluginInstance& plugin)
            : juce::DocumentWindow(plugin.getName(),
                                   juce::Colours::darkgrey,
                                   juce::DocumentWindow::closeButton)
        {
            setUsingNativeTitleBar(true);
            setResizable(true, true);
            setContentOwned(plugin.createEditorIfNeeded(), true);
            centreWithSize(getWidth(), getHeight());
            setVisible(true);
        }

        void closeButtonPressed() override { setVisible(false); }
    };

    PluginHost pluginHost;
    OfflineProcessor processor;

    juce::Label pluginLabel;
    juce::Label inputLabel;
    juce::Label outputLabel;
    juce::Label blockSizeLabel;

    juce::TextEditor blockSizeEditor;

    juce::TextButton loadPluginButton;
    juce::TextButton openEditorButton;
    juce::TextButton inputButton;
    juce::TextButton outputButton;
    juce::TextButton processButton;
    juce::TextButton arrayProcessButton;

    juce::File inputFile;
    juce::File outputFile;

    std::unique_ptr<PluginEditorWindow> editorWindow;
    std::unique_ptr<ArrayProcessWindow> arrayWindow;
};

class WebMainComponent final : public juce::Component
{
public:
    WebMainComponent()
        : webRoot(findWebRoot()),
          processor(pluginHost),
          browser(makeBrowserOptions())
    {
        addAndMakeVisible(browser);
        browser.goToURL(juce::WebBrowserComponent::getResourceProviderRoot());
        setSize(980, 720);
    }

    void resized() override
    {
        browser.setBounds(getLocalBounds());
    }

private:
    static juce::String getMimeTypeForFile(const juce::File& file)
    {
        const auto ext = file.getFileExtension().toLowerCase();

        if (ext == ".html" || ext == ".htm")
            return "text/html; charset=utf-8";
        if (ext == ".js" || ext == ".mjs")
            return "text/javascript; charset=utf-8";
        if (ext == ".css")
            return "text/css; charset=utf-8";
        if (ext == ".json")
            return "application/json; charset=utf-8";
        if (ext == ".svg")
            return "image/svg+xml";
        if (ext == ".png")
            return "image/png";
        if (ext == ".jpg" || ext == ".jpeg")
            return "image/jpeg";
        if (ext == ".woff")
            return "font/woff";
        if (ext == ".woff2")
            return "font/woff2";

        return "application/octet-stream";
    }

    static std::vector<std::byte> loadBytesFromFile(const juce::File& file)
    {
        juce::MemoryBlock mb;
        if (!file.loadFileAsData(mb))
            return {};

        std::vector<std::byte> out;
        out.resize(mb.getSize());
        if (mb.getSize() > 0)
            std::memcpy(out.data(), mb.getData(), mb.getSize());
        return out;
    }

    juce::File findWebRoot() const
    {
        auto tryFindFrom = [](juce::File dir) -> juce::File
        {
            for (int i = 0; i < 10; ++i)
            {
                const auto dist = dir.getChildFile("webui").getChildFile("dist");
                if (dist.getChildFile("index.html").existsAsFile())
                    return dist;

                const auto src = dir.getChildFile("webui").getChildFile("src");
                if (src.getChildFile("index.html").existsAsFile())
                    return src;

                const auto parent = dir.getParentDirectory();
                if (parent == dir)
                    break;
                dir = parent;
            }

            return {};
        };

        if (const auto fromCwd = tryFindFrom(juce::File::getCurrentWorkingDirectory()); fromCwd.exists())
            return fromCwd;

        const auto exeDir = juce::File::getSpecialLocation(juce::File::currentApplicationFile).getParentDirectory();
        if (const auto fromExe = tryFindFrom(exeDir); fromExe.exists())
            return fromExe;

        return {};
    }

    std::optional<juce::WebBrowserComponent::Resource> provideResource(const juce::String& path) const
    {
        if (!webRoot.exists())
            return std::nullopt;

        auto requestPath = path.isEmpty() ? "/" : path;
        if (!requestPath.startsWithChar('/'))
            requestPath = "/" + requestPath;

        if (requestPath.contains(".."))
            return std::nullopt;

        if (requestPath == "/")
            requestPath = "/index.html";

        const auto relative = requestPath.substring(1);
        const auto file = webRoot.getChildFile(relative);
        if (!file.existsAsFile())
            return std::nullopt;

        juce::WebBrowserComponent::Resource res;
        res.data = loadBytesFromFile(file);
        if (res.data.empty())
            return std::nullopt;

        res.mimeType = getMimeTypeForFile(file);
        return res;
    }

    juce::WebBrowserComponent::Options makeBrowserOptions()
    {
        auto options = juce::WebBrowserComponent::Options{}
                           .withBackend(juce::WebBrowserComponent::Options::Backend::webview2)
                           .withNativeIntegrationEnabled()
                           .withResourceProvider(
                               [this](const juce::String& path) -> std::optional<juce::WebBrowserComponent::Resource>
                               {
                                   return provideResource(path);
                               })
                           .withNativeFunction("refreshState",
                                               [this](const juce::Array<juce::var>&, juce::WebBrowserComponent::NativeFunctionCompletion completion)
                                               {
                                                   completion(makeStateVar());
                                               })
                           .withNativeFunction("setBlockSize",
                                               [this](const juce::Array<juce::var>& args, juce::WebBrowserComponent::NativeFunctionCompletion completion)
                                               {
                                                   if (args.size() < 1)
                                                   {
                                                       completion(makeErrorVar(u8str(u8"\u7f3a\u5c11 blockSize")));
                                                       return;
                                                   }

                                                   const int newBlockSize = juce::jmax(64, static_cast<int>(args[0]));
                                                   lastBlockSize = newBlockSize;
                                                   processor.setBlockSize(newBlockSize);
                                                   completion(makeStateVar());
                                               })
                           .withNativeFunction("choosePlugin",
                                               [this](const juce::Array<juce::var>&, juce::WebBrowserComponent::NativeFunctionCompletion completion)
                                               {
                                                   juce::FileChooser chooser(u8str(u8"\u9009\u62e9\u63d2\u4ef6\u6587\u4ef6\uff08VST3\uff09"), {}, "*.vst3");
                                                   if (!chooser.browseForFileToOpen())
                                                   {
                                                       completion(makeStateVar());
                                                       return;
                                                   }

                                                   const auto file = chooser.getResult();
                                                   juce::String error;
                                                   if (!pluginHost.loadPluginFromFile(file, 44100.0, lastBlockSize, error))
                                                   {
                                                       completion(makeErrorVar(error));
                                                       return;
                                                   }

                                                   completion(makeStateVar());
                                               })
                           .withNativeFunction("openPluginEditor",
                                               [this](const juce::Array<juce::var>&, juce::WebBrowserComponent::NativeFunctionCompletion completion)
                                               {
                                                   auto* plugin = pluginHost.get();
                                                   if (plugin == nullptr)
                                                   {
                                                       completion(makeErrorVar(u8str(u8"\u8bf7\u5148\u52a0\u8f7d\u63d2\u4ef6")));
                                                       return;
                                                   }

                                                   if (!plugin->hasEditor())
                                                   {
                                                       completion(makeErrorVar(u8str(u8"\u8be5\u63d2\u4ef6\u6ca1\u6709\u754c\u9762")));
                                                       return;
                                                   }

                                                   editorWindow.reset();
                                                   editorWindow = std::make_unique<PluginEditorWindow>(*plugin);
                                                   completion(makeOkVar());
                                               })
                           .withNativeFunction("chooseInputAudio",
                                               [this](const juce::Array<juce::var>&, juce::WebBrowserComponent::NativeFunctionCompletion completion)
                                               {
                                                   juce::FileChooser chooser(u8str(u8"\u9009\u62e9\u8f93\u5165\u97f3\u9891\u6587\u4ef6"), {}, "*.wav;*.aiff;*.aif;*.flac;*.mp3");
                                                   if (!chooser.browseForFileToOpen())
                                                   {
                                                       completion(makeStateVar());
                                                       return;
                                                   }

                                                   inputFile = chooser.getResult();
                                                   completion(makeStateVar());
                                               })
                           .withNativeFunction("chooseOutputAudio",
                                               [this](const juce::Array<juce::var>&, juce::WebBrowserComponent::NativeFunctionCompletion completion)
                                               {
                                                   juce::FileChooser chooser(u8str(u8"\u9009\u62e9\u8f93\u51fa WAV \u6587\u4ef6"), {}, "*.wav");
                                                   if (!chooser.browseForFileToSave(true))
                                                   {
                                                       completion(makeStateVar());
                                                       return;
                                                   }

                                                   outputFile = chooser.getResult().withFileExtension("wav");
                                                   completion(makeStateVar());
                                               })
                           .withNativeFunction("startProcess",
                                               [this](const juce::Array<juce::var>&, juce::WebBrowserComponent::NativeFunctionCompletion completion)
                                               {
                                                   auto* plugin = pluginHost.get();
                                                   if (plugin == nullptr)
                                                   {
                                                       completion(makeErrorVar(u8str(u8"\u8bf7\u5148\u52a0\u8f7d\u63d2\u4ef6")));
                                                       return;
                                                   }

                                                   if (!inputFile.existsAsFile())
                                                   {
                                                       completion(makeErrorVar(u8str(u8"\u8bf7\u5148\u9009\u62e9\u8f93\u5165\u97f3\u9891")));
                                                       return;
                                                   }

                                                   if (outputFile.getFullPathName().isEmpty())
                                                   {
                                                       completion(makeErrorVar(u8str(u8"\u8bf7\u5148\u9009\u62e9\u8f93\u51fa\u8def\u5f84")));
                                                       return;
                                                   }

                                                   processor.setBlockSize(lastBlockSize);
                                                   ProcessorThread thread(processor, inputFile, outputFile);
                                                   thread.runThread();

                                                   if (!thread.ok)
                                                   {
                                                       completion(makeErrorVar(thread.error));
                                                       return;
                                                   }

                                                   auto result = makeOkVar();
                                                   if (auto* obj = result.getDynamicObject())
                                                   {
                                                       auto stats = std::make_unique<juce::DynamicObject>();
                                                       stats->setProperty("outputChannels", thread.stats.outputChannels);
                                                       stats->setProperty("inputRmsDb", thread.stats.inputRmsDb);
                                                       stats->setProperty("diffRmsDb", thread.stats.diffRmsDb);
                                                       stats->setProperty("maxAbsDiff", thread.stats.maxAbsDiff);
                                                       obj->setProperty("stats", juce::var(stats.release()));
                                                       obj->setProperty("outputPath", outputFile.getFullPathName());
                                                   }
                                                   completion(result);
                                               })
                           .withNativeFunction("processArray",
                                               [this](const juce::Array<juce::var>& args, juce::WebBrowserComponent::NativeFunctionCompletion completion)
                                               {
                                                   auto* plugin = pluginHost.get();
                                                   if (plugin == nullptr)
                                                   {
                                                       completion(makeErrorVar(u8str(u8"\u8bf7\u5148\u52a0\u8f7d\u63d2\u4ef6")));
                                                       return;
                                                   }

                                                   if (args.size() < 2)
                                                   {
                                                       completion(makeErrorVar(u8str(u8"\u7f3a\u5c11\u53c2\u6570")));
                                                       return;
                                                   }

                                                   const double sr = static_cast<double>(args[0]);
                                                   const double sampleRate = sr > 0.0 ? sr : 44100.0;
                                                   const juce::String text = args[1].toString();

                                                   juce::String parseError;
                                                   auto input = parseFloatList(text, parseError);
                                                   if (parseError.isNotEmpty())
                                                   {
                                                       completion(makeErrorVar(parseError));
                                                       return;
                                                   }

                                                   if (input.empty())
                                                   {
                                                       completion(makeErrorVar(u8str(u8"\u8bf7\u8f93\u5165\u81f3\u5c11\u4e00\u4e2a float")));
                                                       return;
                                                   }

                                                   juce::String error;
                                                   auto out = processor.processMonoFloatArray(input.data(), static_cast<int>(input.size()), sampleRate, error);
                                                   if (error.isNotEmpty())
                                                   {
                                                       completion(makeErrorVar(error));
                                                       return;
                                                   }

                                                   auto result = makeOkVar();
                                                   if (auto* obj = result.getDynamicObject())
                                                       obj->setProperty("outputText", formatFloatList(out));
                                                   completion(result);
                                               });

        juce::WebBrowserComponent::Options::WinWebView2 winOpts;
        winOpts = winOpts.withStatusBarDisabled()
                      .withBuiltInErrorPageDisabled()
                      .withBackgroundColour(juce::Colours::transparentBlack)
                      .withUserDataFolder(juce::File::getSpecialLocation(juce::File::tempDirectory)
                                              .getChildFile("VSTHostAppWebView2"));
        options = options.withWinWebView2Options(winOpts);

        return options;
    }

    juce::var makeOkVar() const
    {
        auto obj = std::make_unique<juce::DynamicObject>();
        obj->setProperty("ok", true);
        return juce::var(obj.release());
    }

    juce::var makeErrorVar(const juce::String& error) const
    {
        auto obj = std::make_unique<juce::DynamicObject>();
        obj->setProperty("ok", false);
        obj->setProperty("error", error);
        return juce::var(obj.release());
    }

    juce::var makeStateVar() const
    {
        auto obj = std::make_unique<juce::DynamicObject>();
        obj->setProperty("ok", true);
        obj->setProperty("pluginName", pluginHost.get() != nullptr ? pluginHost.getDescription().name : u8str(u8"\u672a\u52a0\u8f7d"));
        obj->setProperty("inputPath", inputFile.getFullPathName());
        obj->setProperty("outputPath", outputFile.getFullPathName());
        obj->setProperty("blockSize", lastBlockSize);
        return juce::var(obj.release());
    }

    class PluginEditorWindow final : public juce::DocumentWindow
    {
    public:
        explicit PluginEditorWindow(juce::AudioPluginInstance& plugin)
            : juce::DocumentWindow(plugin.getName(),
                                   juce::Colours::darkgrey,
                                   juce::DocumentWindow::closeButton)
        {
            setUsingNativeTitleBar(true);
            setResizable(true, true);
            setContentOwned(plugin.createEditorIfNeeded(), true);
            centreWithSize(getWidth(), getHeight());
            setVisible(true);
        }

        void closeButtonPressed() override { setVisible(false); }
    };

    juce::File webRoot;
    PluginHost pluginHost;
    int lastBlockSize = 1024;
    OfflineProcessor processor;

    juce::WebBrowserComponent browser;

    juce::File inputFile;
    juce::File outputFile;

    std::unique_ptr<PluginEditorWindow> editorWindow;
};
} // namespace vsthost

class VSTHostApplication final : public juce::JUCEApplication
{
public:
    const juce::String getApplicationName() override { return "VSTHostApp"; }
    const juce::String getApplicationVersion() override { return "0.1.0"; }
    bool moreThanOneInstanceAllowed() override { return true; }

    void initialise(const juce::String&) override
    {
        mainWindow = std::make_unique<MainWindow>(getApplicationName());
    }

    void shutdown() override
    {
        mainWindow = nullptr;
    }

    void systemRequestedQuit() override
    {
        quit();
    }

    void anotherInstanceStarted(const juce::String&) override {}

private:
    class MainWindow final : public juce::DocumentWindow
    {
    public:
        explicit MainWindow(juce::String name)
            : juce::DocumentWindow(std::move(name),
                                   juce::Desktop::getInstance().getDefaultLookAndFeel()
                                       .findColour(juce::ResizableWindow::backgroundColourId),
                                   juce::DocumentWindow::allButtons)
        {
            setUsingNativeTitleBar(true);
            setContentOwned(new vsthost::WebMainComponent(), true);
            setResizable(true, true);
            centreWithSize(1160, 900);
            setVisible(true);
        }

        void closeButtonPressed() override
        {
            juce::JUCEApplication::getInstance()->systemRequestedQuit();
        }
    };

    std::unique_ptr<MainWindow> mainWindow;
};

START_JUCE_APPLICATION(VSTHostApplication)
