
# 简介
clean_to_wav_configured 用来转换音频文件, 转化为22050采样率 16bit的wav文件,并去除文件头和尾中(adobe)的无关文件
依赖于ffmpeg

amp_tools 有amp有关, 用来处理amp文件,比如wav转数组, 简易浮点数组滤波器处理.

drumbin 主要是鼓机音频文件拼接

vsthost 是一个vst插件主机, 用来加载和运行vst插件.可离线对wav文件或者浮点数组进行处理.通过其中插入的vst插件.

# 注意
vsthost 是一个实验性项目, 目前只支持windows.

依赖github ci/cd工具, 编译exe文件

# 构建 python工具
此项目使用conda进行包管理, 请先安装conda.

1. 克隆项目
2. 进入项目目录
3. 创建conda环境
```bash
conda env create -f environment.yml
```
4. 激活环境
```bash
conda activate drumbin
```

# 构建 vsthost
此项目使用cmake 进行构建. 请先安装cmake.
在window上, 请先安装visual studio.

### web gui npm构建
1. 进入vsthost/web_gui目录
2. 安装依赖
```bash
npm install
```
3. 构建
```bash
npm run build
```

### juce构建
1. 进入vsthost目录

2. 创建build目录
```bash
mkdir build
cd build
```
3. 运行cmake
```bash
cmake ..
```
4. 编译
```bash
cmake --build .
```
