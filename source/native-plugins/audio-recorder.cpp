/*
 * Carla Native Plugins
 * Copyright (C) 2026
 *
 * This program is free software; you can redistribute it and/or
 * modify it under the terms of the GNU General Public License as
 * published by the Free Software Foundation; either version 2 of
 * the License, or any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU General Public License for more details.
 *
 * For a full copy of the GNU General Public License see the doc/GPL.txt file.
 */

#include "CarlaNative.hpp"

#include "water/files/File.h"
#include "water/text/String.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <vector>

using water::File;
using water::String;

// -----------------------------------------------------------------------

static inline int16_t clampFloatToPcm16(const float value) noexcept
{
    const float fixed = std::max(-1.0f, std::min(1.0f, value));
    return static_cast<int16_t>(fixed * 32767.0f);
}

static inline void writeUint16Le(std::FILE* const fileHandle, const uint16_t value)
{
    const unsigned char data[2] = {
        static_cast<unsigned char>(value & 0xffu),
        static_cast<unsigned char>((value >> 8u) & 0xffu),
    };

    std::fwrite(data, 1, sizeof(data), fileHandle);
}

static inline void writeUint32Le(std::FILE* const fileHandle, const uint32_t value)
{
    const unsigned char data[4] = {
        static_cast<unsigned char>(value & 0xffu),
        static_cast<unsigned char>((value >> 8u) & 0xffu),
        static_cast<unsigned char>((value >> 16u) & 0xffu),
        static_cast<unsigned char>((value >> 24u) & 0xffu),
    };

    std::fwrite(data, 1, sizeof(data), fileHandle);
}

// -----------------------------------------------------------------------

class AudioRecorderPlugin : public NativePluginClass
{
public:
    enum Parameters {
        kParameterEnabled,
        kParameterDurationSeconds,
        kParameterPeakLeft,
        kParameterPeakRight,
        kParameterCount
    };

    AudioRecorderPlugin(const NativeHostDescriptor* const host)
        : NativePluginClass(host),
          fEnabled(true),
          fFramesWritten(0),
          fSampleRate(44100),
          fDurationSeconds(0.0f),
          fPeakLeft(0.0f),
          fPeakRight(0.0f),
          fWriter(nullptr),
          fFilename(),
          fInterleavedBuffer() {}

    ~AudioRecorderPlugin() override
    {
        closeWriter();
    }

protected:
    // -------------------------------------------------------------------
    // Plugin parameter calls

    uint32_t getParameterCount() const override
    {
        return kParameterCount;
    }

    const NativeParameter* getParameterInfo(const uint32_t index) const override
    {
        CARLA_SAFE_ASSERT_RETURN(index < kParameterCount, nullptr);

        static NativeParameter param;
        std::memset(&param, 0, sizeof(param));

        param.ranges.def = 0.0f;
        param.ranges.min = 0.0f;
        param.ranges.max = 1.0f;
        param.ranges.step = 1.0f;
        param.ranges.stepSmall = 1.0f;
        param.ranges.stepLarge = 1.0f;

        switch (index)
        {
        case kParameterEnabled:
            param.hints = static_cast<NativeParameterHints>(NATIVE_PARAMETER_IS_ENABLED|
                                                            NATIVE_PARAMETER_IS_AUTOMATABLE|
                                                            NATIVE_PARAMETER_IS_BOOLEAN|
                                                            NATIVE_PARAMETER_USES_DESIGNATION);
            param.name = "Enabled";
            param.designation = NATIVE_PARAMETER_DESIGNATION_ENABLED;
            param.ranges.def = 1.0f;
            break;
        case kParameterDurationSeconds:
            param.hints = static_cast<NativeParameterHints>(NATIVE_PARAMETER_IS_ENABLED|
                                                            NATIVE_PARAMETER_IS_OUTPUT);
            param.name = "Recorded Seconds";
            param.unit = "s";
            param.ranges.max = static_cast<float>(INT32_MAX);
            param.ranges.step = 0.1f;
            param.ranges.stepSmall = 0.01f;
            param.ranges.stepLarge = 1.0f;
            break;
        case kParameterPeakLeft:
            param.hints = static_cast<NativeParameterHints>(NATIVE_PARAMETER_IS_ENABLED|
                                                            NATIVE_PARAMETER_IS_OUTPUT);
            param.name = "Peak Left";
            param.ranges.step = 0.01f;
            param.ranges.stepSmall = 0.001f;
            param.ranges.stepLarge = 0.1f;
            break;
        case kParameterPeakRight:
            param.hints = static_cast<NativeParameterHints>(NATIVE_PARAMETER_IS_ENABLED|
                                                            NATIVE_PARAMETER_IS_OUTPUT);
            param.name = "Peak Right";
            param.ranges.step = 0.01f;
            param.ranges.stepSmall = 0.001f;
            param.ranges.stepLarge = 0.1f;
            break;
        default:
            return nullptr;
        }

        return &param;
    }

    float getParameterValue(const uint32_t index) const override
    {
        switch (index)
        {
        case kParameterEnabled:
            return fEnabled ? 1.0f : 0.0f;
        case kParameterDurationSeconds:
            return fDurationSeconds;
        case kParameterPeakLeft:
            return fPeakLeft;
        case kParameterPeakRight:
            return fPeakRight;
        default:
            return 0.0f;
        }
    }

    // -------------------------------------------------------------------
    // Plugin state calls

    void setParameterValue(const uint32_t index, const float value) override
    {
        if (index == kParameterEnabled)
            fEnabled = (value > 0.5f);
    }

    void setCustomData(const char* const key, const char* const value) override
    {
        CARLA_SAFE_ASSERT_RETURN(key != nullptr && key[0] != '\0',);
        CARLA_SAFE_ASSERT_RETURN(value != nullptr,);

        if (std::strcmp(key, "file") != 0)
            return;

        fFilename = value;

        if (fWriter != nullptr)
            openWriter();
    }

    // -------------------------------------------------------------------
    // Plugin process calls

    void activate() override
    {
        fFramesWritten = 0;
        fDurationSeconds = 0.0f;
        fPeakLeft = 0.0f;
        fPeakRight = 0.0f;

        if (fFilename.isNotEmpty())
            openWriter();
    }

    void deactivate() override
    {
        closeWriter();
    }

    void process(const float* const* const inBuffer,
                 float**,
                 const uint32_t frames,
                 const NativeMidiEvent* const,
                 const uint32_t) override
    {
        if (inBuffer == nullptr || frames == 0)
            return;

        const float* const inputLeft = inBuffer[0];
        const float* const inputRight = inBuffer[1] != nullptr ? inBuffer[1] : inBuffer[0];

        if (inputLeft == nullptr)
            return;

        fPeakLeft = 0.0f;
        fPeakRight = 0.0f;

        for (uint32_t i=0; i < frames; ++i)
        {
            fPeakLeft = std::max(fPeakLeft, static_cast<float>(std::fabs(inputLeft[i])));
            fPeakRight = std::max(fPeakRight, static_cast<float>(std::fabs(inputRight[i])));
        }

        if (! fEnabled || fFilename.isEmpty())
            return;

        const NativeTimeInfo* const timeInfo = getTimeInfo();

        if (timeInfo != nullptr && ! timeInfo->playing)
            return;

        if (fWriter == nullptr)
            openWriter();

        if (fWriter == nullptr)
            return;

        if (fInterleavedBuffer.size() < frames * 2u)
            fInterleavedBuffer.resize(frames * 2u);

        for (uint32_t i=0, j=0; i < frames; ++i, j += 2)
        {
            fInterleavedBuffer[j] = clampFloatToPcm16(inputLeft[i]);
            fInterleavedBuffer[j + 1] = clampFloatToPcm16(inputRight[i]);
        }

        std::fwrite(fInterleavedBuffer.data(), sizeof(int16_t), frames * 2u, fWriter);
        fFramesWritten += frames;

        if (fSampleRate != 0u)
            fDurationSeconds = static_cast<float>(fFramesWritten) / static_cast<float>(fSampleRate);
    }

private:
    bool fEnabled;
    uint64_t fFramesWritten;
    uint32_t fSampleRate;
    float fDurationSeconds;
    float fPeakLeft;
    float fPeakRight;
    std::FILE* fWriter;
    String fFilename;
    std::vector<int16_t> fInterleavedBuffer;

    void openWriter()
    {
        closeWriter();

        if (fFilename.isEmpty())
            return;

        const File outputFile(fFilename);
        const File parentDir(outputFile.getParentDirectory());

        if (! parentDir.exists())
            parentDir.createDirectory();

        fWriter = std::fopen(outputFile.getFullPathName().toRawUTF8(), "wb");

        if (fWriter == nullptr)
            return;

        fFramesWritten = 0;
        fDurationSeconds = 0.0f;
        fSampleRate = static_cast<uint32_t>(getSampleRate() + 0.5);
        writeWaveHeader();
    }

    void closeWriter()
    {
        if (fWriter == nullptr)
            return;

        updateWaveHeaderSizes();
        std::fclose(fWriter);
        fWriter = nullptr;
    }

    void writeWaveHeader()
    {
        CARLA_SAFE_ASSERT_RETURN(fWriter != nullptr,);

        std::fwrite("RIFF", 1, 4, fWriter);
        writeUint32Le(fWriter, 36u);
        std::fwrite("WAVE", 1, 4, fWriter);
        std::fwrite("fmt ", 1, 4, fWriter);
        writeUint32Le(fWriter, 16u);
        writeUint16Le(fWriter, 1u);
        writeUint16Le(fWriter, 2u);
        writeUint32Le(fWriter, fSampleRate);
        writeUint32Le(fWriter, fSampleRate * 2u * sizeof(int16_t));
        writeUint16Le(fWriter, static_cast<uint16_t>(2u * sizeof(int16_t)));
        writeUint16Le(fWriter, static_cast<uint16_t>(8u * sizeof(int16_t)));
        std::fwrite("data", 1, 4, fWriter);
        writeUint32Le(fWriter, 0u);
    }

    void updateWaveHeaderSizes()
    {
        CARLA_SAFE_ASSERT_RETURN(fWriter != nullptr,);

        const uint32_t dataSize = static_cast<uint32_t>(fFramesWritten * 2u * sizeof(int16_t));
        const uint32_t riffSize = 36u + dataSize;

        std::fseek(fWriter, 4, SEEK_SET);
        writeUint32Le(fWriter, riffSize);

        std::fseek(fWriter, 40, SEEK_SET);
        writeUint32Le(fWriter, dataSize);

        std::fflush(fWriter);
    }

    PluginClassEND(AudioRecorderPlugin)
    CARLA_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(AudioRecorderPlugin)
};

// -----------------------------------------------------------------------

static const NativePluginDescriptor audiorecorderDesc = {
    /* category  */ NATIVE_PLUGIN_CATEGORY_UTILITY,
    /* hints     */ static_cast<NativePluginHints>(NATIVE_PLUGIN_USES_TIME),
    /* supports  */ NATIVE_PLUGIN_SUPPORTS_NOTHING,
    /* audioIns  */ 2,
    /* audioOuts */ 0,
    /* midiIns   */ 0,
    /* midiOuts  */ 0,
    /* paramIns  */ 1,
    /* paramOuts */ 3,
    /* name      */ "Audio Recorder",
    /* label     */ "audiorecorder",
    /* maker     */ "OpenAI",
    /* copyright */ "GNU GPL v2+",
    PluginDescriptorFILL(AudioRecorderPlugin)
};

// -----------------------------------------------------------------------

CARLA_API_EXPORT
void carla_register_native_plugin_audiorecorder();

CARLA_API_EXPORT
void carla_register_native_plugin_audiorecorder()
{
    carla_register_native_plugin(&audiorecorderDesc);
}

// -----------------------------------------------------------------------
