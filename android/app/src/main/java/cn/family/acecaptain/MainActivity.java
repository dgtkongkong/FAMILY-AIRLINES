package cn.family.acecaptain;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Bundle;
import android.net.Uri;
import android.view.View;
import android.view.WindowInsets;
import android.widget.*;
import android.webkit.*;
import android.content.Intent;
import java.net.HttpURLConnection;
import java.net.URL;
import java.io.InputStream;
import java.io.OutputStream;

/** Shared authenticated web client for Seewo XT01E and Android phones. */
public class MainActivity extends Activity {
    private WebView web;
    private String origin;
    private String pendingDownload;
    private String pendingCookie;
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        String saved = getPreferences(MODE_PRIVATE).getString("server", BuildConfig.DEFAULT_SERVER_URL);
        if (saved.isEmpty()) configure(); else open(saved);
    }
    private void configure() {
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        int pad = (int)(24 * getResources().getDisplayMetrics().density);
        layout.setPadding(pad,pad,pad,pad);
        TextView title = new TextView(this);
        title.setText("✈ 王牌机长\n连接家庭塔台");title.setTextSize(26);
        layout.addView(title);
        TextView help = new TextView(this);
        help.setText("输入已部署的服务器网址，然后使用孩子、爸爸或妈妈账号登录。" + (BuildConfig.DEBUG ? "\n测试包支持家庭局域网 HTTP。" : "\n正式版仅允许 HTTPS。"));
        layout.addView(help);
        EditText address = new EditText(this);
        address.setSingleLine(true);address.setHint("https://captain.example.com");
        address.setInputType(android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_VARIATION_URI);
        address.setText(getPreferences(MODE_PRIVATE).getString("server",""));layout.addView(address);
        Button button = new Button(this);button.setText("连接塔台");layout.addView(button);
        button.setOnClickListener(v -> {
            String url=address.getText().toString().trim();Uri uri=Uri.parse(url);
            boolean valid="https".equals(uri.getScheme()) || (BuildConfig.DEBUG && "http".equals(uri.getScheme()));
            if (!valid || uri.getHost()==null || uri.getUserInfo()!=null || uri.getQuery()!=null || uri.getFragment()!=null || (uri.getPath()!=null && !uri.getPath().isEmpty() && !"/".equals(uri.getPath()))) {
                address.setError("请输入有效的塔台根网址，正式版必须使用 HTTPS");return;
            }
            origin=uri.getScheme()+"://"+uri.getEncodedAuthority();
            getPreferences(MODE_PRIVATE).edit().putString("server",origin).apply();open(origin);
        });
        setContentView(layout);
    }
    private boolean allowed(String url) {
        Uri a=Uri.parse(origin),b=Uri.parse(url);
        return a.getScheme().equals(b.getScheme()) && a.getEncodedAuthority().equals(b.getEncodedAuthority());
    }
    private void open(String url) {
        origin=url;
        LinearLayout layout=new LinearLayout(this);layout.setOrientation(LinearLayout.VERTICAL);
        layout.setOnApplyWindowInsetsListener((v,insets)->{
            if(android.os.Build.VERSION.SDK_INT>=30){android.graphics.Insets bars=insets.getInsets(WindowInsets.Type.systemBars());v.setPadding(bars.left,bars.top,bars.right,bars.bottom);}
            return insets;
        });
        Button settings=new Button(this);settings.setText("✈ 家庭塔台 · 更换服务器");
        settings.setOnClickListener(v->new AlertDialog.Builder(this).setMessage("更换塔台网址？当前服务器登录状态将被清除。")
            .setPositiveButton("更换",(d,w)->{CookieManager.getInstance().removeAllCookies(null);web.destroy();configure();}).setNegativeButton("取消",null).show());
        layout.addView(settings);
        web=new WebView(this);layout.addView(web,new LinearLayout.LayoutParams(-1,0,1));
        WebSettings ws=web.getSettings();ws.setJavaScriptEnabled(true);ws.setDomStorageEnabled(true);
        ws.setUserAgentString(ws.getUserAgentString()+" AceCaptainAndroid/1.1");
        ws.setAllowFileAccess(false);ws.setAllowContentAccess(false);ws.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        CookieManager.getInstance().setAcceptCookie(true);CookieManager.getInstance().setAcceptThirdPartyCookies(web,false);
        // Native bridge deliberately absent. JavaScript dialogs are needed for confirmations.
        web.setWebChromeClient(new WebChromeClient());
        web.setDownloadListener((target,userAgent,disposition,mime,length)->{
            if(!allowed(target))return;
            pendingDownload=target;pendingCookie=CookieManager.getInstance().getCookie(target);
            Intent save=new Intent(Intent.ACTION_CREATE_DOCUMENT);
            save.addCategory(Intent.CATEGORY_OPENABLE);
            save.setType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
            save.putExtra(Intent.EXTRA_TITLE,"家庭航程账本-"+System.currentTimeMillis()+".xlsx");
            startActivityForResult(save,41);
        });
        web.setWebViewClient(new WebViewClient(){
            @Override public boolean shouldOverrideUrlLoading(WebView view,String target){return !allowed(target);}
            @Override public void onReceivedError(WebView view,WebResourceRequest request,WebResourceError error){
                if(request.isForMainFrame())Toast.makeText(MainActivity.this,"塔台暂时未连接，请检查网络或服务器网址",Toast.LENGTH_LONG).show();
            }
            @Override public void onPageFinished(WebView view,String loaded){CookieManager.getInstance().flush();}
        });
        setContentView(layout);web.loadUrl(origin+"/");
    }
    @Override public void onBackPressed(){if(web!=null&&web.canGoBack())web.goBack();else super.onBackPressed();}
    @Override protected void onActivityResult(int request,int result,Intent data){
        super.onActivityResult(request,result,data);
        if(request!=41)return;
        final String target=pendingDownload,cookie=pendingCookie;
        pendingDownload=null;pendingCookie=null;
        if(result!=RESULT_OK||data==null||data.getData()==null||target==null)return;
        final Uri destination=data.getData();
        new Thread(()->{
            HttpURLConnection connection=null;
            try{
                connection=(HttpURLConnection)new URL(target).openConnection();
                connection.setInstanceFollowRedirects(false);
                connection.setConnectTimeout(15000);connection.setReadTimeout(30000);
                if(cookie!=null)connection.setRequestProperty("Cookie",cookie);
                if(connection.getResponseCode()!=200)throw new java.io.IOException("Export rejected");
                try(InputStream input=connection.getInputStream();OutputStream output=getContentResolver().openOutputStream(destination)){
                    if(output==null)throw new java.io.IOException("No destination");
                    byte[] bytes=new byte[8192];int count;while((count=input.read(bytes))!=-1)output.write(bytes,0,count);
                }
                runOnUiThread(()->Toast.makeText(this,"Excel 已保存",Toast.LENGTH_LONG).show());
            }catch(Exception e){runOnUiThread(()->Toast.makeText(this,"导出未完成，请检查网络并重新登录后重试",Toast.LENGTH_LONG).show());}
            finally{if(connection!=null)connection.disconnect();}
        }).start();
    }
    @Override protected void onDestroy(){if(web!=null)web.destroy();super.onDestroy();}
}
