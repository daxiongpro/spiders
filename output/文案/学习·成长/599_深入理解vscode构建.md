# 深入理解vscode构建

- 链接：https://www.douyin.com/video/7546587290806586651
- 原文件夹：未分类
- 新分类：学习·成长
- 点赞数：937
- 相关主题：编程开发/VSCode

## 口播逐字稿

Speaker 1 00:00:00.120 
今天我们来从宏观的角度理解 VS Code 的源代码，我们需要了解构建流水线是如何运作的。首先 VS Code 是一个 NodeJS 的项目，每个 NodeJS 的项目都需要先运行 npm install。我们来到代码中，打开 package. json，我们可以看到 npm install 有三个阶段，首先是 npm preinstall， VS Code 的 preinstall 脚本实际上是 build npm preinstall. js。我们打开 preinstall. js，这个脚本的主要作用是检查NodeJS、 Python 和C、 C + + 编译器工具链版本，主要用于nodejpe。 nodejpe 是什么呢？我们可以打开 nodejpe 的官网主页。

Speaker 1 00:00:48.310 
nodejpe 是 NodeJS 的原生的扩展构建工具，在 VS Code 的项目代码中，最让你感觉困惑的可能就是 nodejpe 了。 VS Code 在性能关键的部分会使用 NodeJS 的原生插件，比如说日志记录的时候会使用 C + + SPDLOG 库。

Speaker 1 00:01:10.530 
spd log，我们可以点开 spd log，在它的目录中，我们可以看到它的 source 里面是 C 加加的代码，所以我们需要使用 nodejip 将这些 C 加加代码构建成与 Electron 以及 NodeJS ABI 二进制接口相匹配的二进制插件。在 pre install 之后的阶段就是普通的 npm install 过程，就是将依赖项下载到 node modules 里面。而最后的 npm post install 就是最复杂的部分，它运行的是。

Speaker 1 00:01:44.400 
build npm post install 脚本，我们打开 post install，我们跳过前面的定义的函数，直接来到最核心的部分。可以看到它的主体代码最外层是一个 for 循环，遍历每个目录。我们可以在 dirs 里面可以看到这些所有的目录。

Speaker 1 00:02:03.280 
你会看到这些目录，其实是因为 VS Code 并没有采用现代化的工作区管理解决方案，比如像 NPM 的workspaces，或者是 PNPM 的workspaces，所以它选择了在 post install。 js 里面去手动处理每个子项目。所以我们回到 post install 的脚本中可以看到，它实际执行的就是两个步骤，一个是 npm install，就是直接在子项目中去进行 npm install。第二个是 set npmrc config，这个就是点 npmrc 文件， nodejs 在构建原生插件的时候会使用这个配置。所以如果每个插件或者是子项目里面用到了 nodejs 的原生插件，就需要依赖于这个npmrc。总结一下，我们可以看到 VS Code 的 install 过程分为三个阶段。 preinstall 去检查前置条件，设置用于构建编译 NodeJS 原生插件的环境。第二部分是普通的 NPM install，就是下载依赖项。

Speaker 1 00:03:09.280 
第三步， postinstall 作为工作区管理的一个脚本，在每个子项目中重复前面的 preinstall 和 install 的两个步骤。在 NPM install 完成以后，你可以运行。 code 点sh。在 scripts code 点 sh 中，来去编译和运行 VS Code。因为 VS Code 是一个 Electron 应用，所以它需要下载预编译好的 Electron 二进制文件。在这个脚本中，我们可以往下滚动，我们可以看到的主体逻辑是 code 逻辑。在主代码里面，你会看到它在调用 code 这个函数，我们回到 code 这个函数，它会先去调用 build lib prelaunch 点js，我们打开 prelaunch 点ts。我们看到 prelaunch 点 ts 的 main 函数里面，主要分为这么几个步骤。第一个， ensure node modules，就是检查 node modules 目录是否存在，如果不存在就会执行 npm ci。我们刚才的安装步骤。

Speaker 1 00:04:21.940 
第二个步骤就是 get electron，就是运行 npm run electron 去下载预构建的 electron 二进制文件。第三步就是 ensure compiled，就是确保 VS Code 已经被编译过了，就是检查 out 目录，如果没有 out 目录，就会再运行一遍 npm run compile。接着 await built in extensions，就是将内置扩展去复制到对应的目录里面。

Speaker 1 00:04:48.900 
在整个 prelaunch 完成以后，我们可以看到它会调用 dollar code 来去运行 electron 的主进程，这个时候你就会看到 VS Code 的窗口就弹出来了。我们 VS Code 的构建和运行就完成了。如果你想了解更多关于 VS Code 开发相关的知识，关注北望智能，我们下期再见！

## 关键词

插件、目录、脚本、子项目、函数、源代码、二进制文件、编译器工具链
