/* Shared local voice pipeline for the Talk view and the 3D world. */
export const VOICE_MAX_MS = 45000;

export async function startVoiceCapture({onLimit=()=>{}}={}){
  if(!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder)
    throw new Error("This browser cannot record microphone audio.");
  const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true}});
  let recorder;
  try{ recorder=new MediaRecorder(stream); }
  catch(e){ stream.getTracks().forEach(t=>t.stop()); throw e; }
  const chunks=[];
  let cancelRequested=false, timer=null;
  const done=new Promise((resolve,reject)=>{
    recorder.ondataavailable=ev=>{if(ev.data&&ev.data.size)chunks.push(ev.data);};
    recorder.onerror=()=>reject(new Error("Microphone recording failed."));
    recorder.onstop=async()=>{
      if(timer)clearTimeout(timer);
      stream.getTracks().forEach(t=>t.stop());
      if(cancelRequested){resolve(null);return;}
      try{
        const blob=new Blob(chunks,{type:recorder.mimeType||"audio/webm"});
        resolve(await audioBlobToWav(blob));
      }catch(e){reject(e);}
    };
  });
  recorder.start(250);
  timer=setTimeout(()=>{
    if(recorder.state!=="inactive"){
      try{recorder.stop();}catch(e){}
      onLimit();
    }
  },VOICE_MAX_MS);
  return {
    stop(){if(recorder.state!=="inactive")recorder.stop();return done;},
    cancel(){cancelRequested=true;if(recorder.state!=="inactive")recorder.stop();return done;},
    done,
  };
}

export async function audioBlobToWav(blob){
  const AudioCtx=window.AudioContext||window.webkitAudioContext;
  if(!AudioCtx)throw new Error("This browser does not support local audio decoding.");
  const ctx=new AudioCtx();let decoded;
  try{decoded=await ctx.decodeAudioData(await blob.arrayBuffer());}
  finally{await ctx.close();}
  const rate=16000,count=Math.floor(decoded.length*rate/decoded.sampleRate);
  if(!count)throw new Error("The recording was empty.");
  const mono=new Float32Array(decoded.length);
  for(let c=0;c<decoded.numberOfChannels;c++){
    const src=decoded.getChannelData(c);
    for(let i=0;i<src.length;i++)mono[i]+=src[i]/decoded.numberOfChannels;
  }
  const buffer=new ArrayBuffer(44+count*2),view=new DataView(buffer);
  const put=(offset,text)=>{for(let i=0;i<text.length;i++)view.setUint8(offset+i,text.charCodeAt(i));};
  put(0,"RIFF");view.setUint32(4,36+count*2,true);put(8,"WAVE");put(12,"fmt ");
  view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);
  view.setUint32(24,rate,true);view.setUint32(28,rate*2,true);view.setUint16(32,2,true);view.setUint16(34,16,true);
  put(36,"data");view.setUint32(40,count*2,true);
  const step=decoded.sampleRate/rate;
  for(let i=0;i<count;i++){
    const at=i*step,lo=Math.floor(at),hi=Math.min(lo+1,mono.length-1),f0=at-lo;
    const v=Math.max(-1,Math.min(1,mono[lo]*(1-f0)+mono[hi]*f0));
    view.setInt16(44+i*2,v<0?v*32768:v*32767,true);
  }
  return new Blob([buffer],{type:"audio/wav"});
}

export async function sendVoiceTurn(name,wav,signal){
  const response=await fetch("/api/voice/"+encodeURIComponent(name)+"/turn",{
    method:"POST",headers:{"Content-Type":"audio/wav"},body:wav,signal,
  });
  const data=await response.json();
  if(!response.ok)throw new Error((data&&data.error)||"The voice turn failed.");
  return data;
}

export function audioURLFromResponse(data){
  if(!data||!data.audio_base64)return null;
  const raw=atob(data.audio_base64),bytes=new Uint8Array(raw.length);
  for(let i=0;i<raw.length;i++)bytes[i]=raw.charCodeAt(i);
  return URL.createObjectURL(new Blob([bytes],{type:data.audio_mime||"audio/wav"}));
}
