"""Build a signed HTTPS APK with official SDK tools, without Gradle downloads.

Requires JAVA_HOME, ANDROID_HOME, CAPTAIN_KEYSTORE, CAPTAIN_STORE_PASSWORD.
The keystore must contain alias captain. Keep it outside the source repository.
"""
import os, subprocess, pathlib, zipfile, shutil

root = pathlib.Path(__file__).resolve().parent
sdk = pathlib.Path(os.environ['ANDROID_HOME'])
java = pathlib.Path(os.environ['JAVA_HOME']) / 'bin'
bt = sdk / 'build-tools' / '35.0.0'
platform = sdk / 'platforms' / 'android-35' / 'android.jar'
out = root / 'build' / 'sdk'
out.mkdir(parents=True, exist_ok=True)

def run(*args):
    subprocess.run([str(x) for x in args], check=True)

manifest = (root / 'app/src/main/AndroidManifest.xml').read_text('utf-8')
manifest = manifest.replace('<manifest ', '<manifest package="cn.family.acecaptain" android:versionCode="2" android:versionName="1.1.0" ', 1)
manifest = manifest.replace('<uses-permission', '<uses-sdk android:minSdkVersion="23" android:targetSdkVersion="35"/><uses-permission', 1)
(out / 'AndroidManifest.xml').write_text(manifest, encoding='utf-8')
run(bt/'aapt2.exe', 'compile', '--dir', root/'app/src/main/res', '-o', out/'resources.zip')
generated = out/'generated'; generated.mkdir(exist_ok=True)
run(bt/'aapt2.exe', 'link', '-o', out/'unsigned.apk', '-I', platform, '--manifest', out/'AndroidManifest.xml', '--java', generated, out/'resources.zip')
config = generated/'cn/family/acecaptain/BuildConfig.java'
config.parent.mkdir(parents=True, exist_ok=True)
config.write_text('package cn.family.acecaptain; public final class BuildConfig { public static final boolean DEBUG=false; public static final String DEFAULT_SERVER_URL=""; }', encoding='utf-8')
classes=out/'classes'; classes.mkdir(exist_ok=True)
sources=list((root/'app/src/main/java').rglob('*.java'))+list(generated.rglob('*.java'))
run(java/'javac.exe', '-encoding', 'UTF-8', '-source', '8', '-target', '8', '-classpath', platform, '-d', classes, *sources)
jar=out/'classes.jar'
with zipfile.ZipFile(jar,'w') as z:
    for f in classes.rglob('*.class'): z.write(f, f.relative_to(classes))
run(java/'java.exe','-cp',bt/'lib/d8.jar','com.android.tools.r8.D8','--release','--min-api','23','--lib',platform,'--output',out,jar)
with zipfile.ZipFile(out/'unsigned.apk','a',zipfile.ZIP_DEFLATED) as z: z.write(out/'classes.dex','classes.dex')
run(bt/'zipalign.exe','-f','4',out/'unsigned.apk',out/'aligned.apk')
apk=out/'ace-captain-1.1.0.apk'
run(java/'java.exe','-jar',bt/'lib/apksigner.jar','sign','--ks',os.environ['CAPTAIN_KEYSTORE'],'--ks-key-alias','captain','--ks-pass','env:CAPTAIN_STORE_PASSWORD','--out',apk,out/'aligned.apk')
run(java/'java.exe','-jar',bt/'lib/apksigner.jar','verify','--verbose',apk)
print('Signed APK:',apk)

