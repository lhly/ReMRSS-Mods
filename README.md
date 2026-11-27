# ReMRSS Mod 社区目录

ReMRSS 新版读取本仓库 `main/index.signed.json` 并验证维护者签名；旧客户端仍读取 `main/index.json`。ZIP 由作者的公开 GitHub Release 提供；App 下载后仍会验签，并请用户审核能力。

<a id="submit"></a>
## 投稿

1. 用 ReMRSS Mod kit 打包签名。上传 ZIP 到自己公开仓库的某一版 GitHub Release，复制附件地址，不用 `latest` 链接。
2. Fork 本仓库，生成投稿记录。以宿主的 `versionCode` 指定最低支持版本；不要填 Mod 自身版本号。

   ```sh
   python3 catalog.py entry ./my-mod.zip \
       https://github.com/AUTHOR/REPO/releases/download/v1.0.0/my-mod.zip \
       --summary '用一句话说明这个 Mod 的用途' --min-host-version-code 2027 \
       > entries/my-mod.json
   python3 catalog.py build
   ```

3. 提交只修改 `entries/<Mod ID>.json` 和 `index.json` 的 PR，附使用说明、来源及能力用途。不要上传签名私钥。
4. 维护者核对来源、用途和能力后合并。升级时沿用 Mod ID 和作者私钥，递增 `versionCode`，使用新的 Release 附件。

## 审核与下架

检查任务从受保护的基线读取校验器，只把候选目录当数据；不执行包中脚本。检查新附件的大小、SHA-256、签名、包格式及目录与签名清单的一致性。人工审核仍需看内容、权限和来源。

紧急下架在原记录设 `"withdrawn": true`，重新生成目录。不要删除记录；保留作者指纹与最后审核版本。App 读取更新后的社区目录时不再展示它，本机已安装的版本不受影响。GitHub 下载不可用时，可用 App 原有的本地 ZIP 导入。


## 部署独立仓库

从 ReMRSS 源码运行 `sdk/mod/prepare-community-repository.sh NEW_DIRECTORY`，会准备校验器、工作流、投稿模板与空目录。将生成的文件提交到 `lhly/ReMRSS-Mods` 的 `main`。保护 `main`：要求 PR、`Verify Mod catalogue / verify` 检查和代码所有者审批；限制直接推送。无需 Pages 或 App Token。

## 体验社区预览

在 ReMRSS 的「模块 → 浏览社区」中安装「电量面板」。要体验同作者升级，先从 `community-preview-v1` 下载 `remrss-counter-0.1.0.zip`，通过「选择 ZIP 文件」导入，再从社区更新计数器。新增的可选能力默认关闭。

## 发布已审核的签名目录

投稿者不需要签目录。目录维护者从已合并的 `main` 签名；这里的私钥与每个 Mod 的作者私钥独立保管。App 固定信任维护者的目录公钥，换钥需要同步更新 App。不要将私钥加入 Git 或发布资产。

```sh
python3 catalog_signature.py sign . --key /secure/catalog-private.pem --public-key catalog-public.pem
python3 catalog_signature.py verify . --public-key catalog-public.pem
```

通过独立的目录发布 PR 提交 `index.signed.json`，不改已审核的条目。`index.json` 为旧版本保留；新的 App 在两种网络模式下都只接受签名目录，目录签名失败不会退回明文。签署时基于当前 `main`（含上次签名文件），避免使用旧工作树发布。序号递增，App 拒绝比本机已核验版本更旧的目录。首次访问还没有本机序号，不能据此判断镜像是否滞后。
