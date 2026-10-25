/* SPDX-License-Identifier: MIT */
/* Opt-in bounded readback of real window-server draws. This diagnostic pays
 * real fences and maps only genuine linear BOs; it is not an FPS benchmark. */
#include <sys/sysctl.h>
#include <unistd.h>
static struct {
   bool checked,enabled;
   char boot[17];
   unsigned draws,images,attempts,seen_count;
   struct {const struct rwa_texture *texture;uint32_t crc,alpha_crc;unsigned role;} seen[128];
} redfin_composition_trace;

static bool
rwa_redfin_trace_selected(void)
{
   if(!redfin_composition_trace.checked) {
      redfin_composition_trace.checked=true;
      const char *option=getenv("REDFIN_METAL_DRAW_CAPTURE"),*name=getprogname();
      if(!option||strcmp(option,"1")||!name||strcmp(name,"backboardd"))return false;
      char args[608]={0};size_t bytes=sizeof(args);
      if(sysctlbyname("kern.bootargs",args,&bytes,NULL,0)||bytes>sizeof(args)||!bytes||args[bytes-1])return false;
      const char *nonce=strstr(args,"redfinbootid=0x");if(!nonce||strlen(nonce+15)<16)return false;
      for(unsigned i=0;i<16;++i) {
         char c=nonce[15+i];if(!((c>='0'&&c<='9')||(c>='a'&&c<='f')))return false;
         redfin_composition_trace.boot[i]=c;
      }
      redfin_composition_trace.enabled=true;
   }
   return redfin_composition_trace.enabled;
}
static uint32_t
rwa_redfin_trace_crc(const uint8_t *bytes,size_t count)
{
   uint32_t crc=UINT32_MAX;
   for(size_t i=0;i<count;++i) {
      crc^=bytes[i];for(unsigned bit=0;bit<8;++bit)crc=(crc>>1)^((0u-(crc&1u))&0xedb88320u);
   }
   return ~crc;
}
static void
rwa_redfin_trace_texture(struct rwa_texture *texture,const char *role,unsigned slot,unsigned draw)
{
   if(!texture||redfin_composition_trace.images>=48||redfin_composition_trace.attempts>=512)return;
   struct rwa_device *device=texture->device;struct pipe_resource *resource=texture->res;
   enum pipe_format format=resource->format;
   if(format_is_depth_stencil(format)||util_format_get_blockwidth(format)!=1||
      util_format_get_blockheight(format)!=1||resource->nr_samples>1||resource->target!=PIPE_TEXTURE_2D)return;
   ++redfin_composition_trace.attempts;
   unsigned pitch=0,offset=0;
   struct pipe_resource *stage=NULL;
   struct pipe_resource *buffer=redfin_freedreno_buffer_alias(device->screen,resource,&pitch,&offset);
   if(!buffer) {
      const struct pipe_resource shape={.target=PIPE_TEXTURE_2D,.format=format,
         .width0=resource->width0,.height0=resource->height0,.depth0=1,.array_size=1,
         .bind=PIPE_BIND_SAMPLER_VIEW|PIPE_BIND_RENDER_TARGET|PIPE_BIND_LINEAR,.usage=PIPE_USAGE_STAGING};
      const uint64_t modifier=DRM_FORMAT_MOD_LINEAR;
      stage=device->screen->resource_create_with_modifiers(device->screen,&shape,&modifier,1);
      struct pipe_box box={.width=resource->width0,.height=resource->height0,.depth=1};char why[192]={0};
      if(stage&&!rwa_blit_native(device,resource,0,&box,stage,0,&box,PIPE_TEX_FILTER_NEAREST,why,sizeof(why)))
         buffer=redfin_freedreno_buffer_alias(device->screen,stage,&pitch,&offset);
      if(!buffer) {
         fprintf(stderr,"REDFIN METAL DRAW IMAGE SKIP: boot=%s draw=%u role=%s slot=%u surface=%u reason=native-readback-refused detail=%s\n",
            redfin_composition_trace.boot,draw,role,slot,texture->redfin_surface,why);
         pipe_resource_reference(&stage,NULL);return;
      }
   }
   unsigned width=resource->width0,height=resource->height0,cpp=util_format_get_blocksize(format);
   if(!width||!height||offset>buffer->width0||
      (uint64_t)(height-1)*pitch+(uint64_t)width*cpp>buffer->width0-offset) {
      pipe_resource_reference(&buffer,NULL);pipe_resource_reference(&stage,NULL);return;
   }
   unsigned w=MIN2(width,80),h=MIN2(MAX2(1,(uint64_t)height*w/width),174);
   size_t raw=(size_t)w*h*3;
   uint8_t *rgb=malloc(raw),*alpha=malloc((size_t)w*h);char *line=malloc(512+raw*4/3+2);
   struct pipe_transfer *transfer=NULL;
   const uint8_t *pixels=rgb&&alpha&&line?pipe_buffer_map(device->pipe,buffer,PIPE_MAP_READ,&transfer):NULL;
   if(!pixels) {free(rgb);free(alpha);free(line);pipe_resource_reference(&buffer,NULL);pipe_resource_reference(&stage,NULL);return;}
   unsigned min_alpha=255,max_alpha=0,zero_alpha=0,opaque=0,invalid_premult=0,zero_nonblack=0,colored=0;
   for(unsigned y=0;y<h;++y)for(unsigned x=0;x<w;++x) {
      unsigned sx=(uint64_t)x*width/w,sy=(uint64_t)y*height/h;uint8_t rgba[4];
      util_format_read_4ub(format,rgba,4,pixels+offset+(uint64_t)sy*pitch+(uint64_t)sx*cpp,cpp,0,0,1,1);
      memcpy(rgb+((size_t)y*w+x)*3,rgba,3);
      alpha[(size_t)y*w+x]=rgba[3];min_alpha=MIN2(min_alpha,rgba[3]);max_alpha=MAX2(max_alpha,rgba[3]);
      zero_alpha+=rgba[3]==0;opaque+=rgba[3]==255;
      invalid_premult+=rgba[0]>rgba[3]+1||rgba[1]>rgba[3]+1||rgba[2]>rgba[3]+1;
      zero_nonblack+=rgba[3]==0&&(rgba[0]||rgba[1]||rgba[2]);
      colored+=rgba[0]||rgba[1]||rgba[2];
   }
   pipe_buffer_unmap(device->pipe,transfer);pipe_resource_reference(&buffer,NULL);pipe_resource_reference(&stage,NULL);
   uint32_t crc=rwa_redfin_trace_crc(rgb,raw);
   uint32_t alpha_crc=rwa_redfin_trace_crc(alpha,(size_t)w*h);
   if(!colored) {
      fprintf(stderr,"REDFIN METAL DRAW SAMPLED-BLACK: boot=%s draw=%u role=%s slot=%u surface=%u samples=%u min-alpha=%u max-alpha=%u alpha-crc32=%08x\n",
         redfin_composition_trace.boot,draw,role,slot,texture->redfin_surface,w*h,min_alpha,max_alpha,alpha_crc);
      free(rgb);free(alpha);free(line);return;
   }
   {
      unsigned kind=!strcmp(role,"OUTPUT");
      unsigned i=0;
      for(;i<redfin_composition_trace.seen_count;++i)
         if(redfin_composition_trace.seen[i].texture==texture&&redfin_composition_trace.seen[i].role==kind)break;
      if(i<redfin_composition_trace.seen_count&&redfin_composition_trace.seen[i].crc==crc&&
         redfin_composition_trace.seen[i].alpha_crc==alpha_crc) {
         free(rgb);free(alpha);free(line);return;
      }
      if(i<128) {
         if(i==redfin_composition_trace.seen_count)++redfin_composition_trace.seen_count;
         redfin_composition_trace.seen[i].texture=texture;redfin_composition_trace.seen[i].crc=crc;
         redfin_composition_trace.seen[i].alpha_crc=alpha_crc;
         redfin_composition_trace.seen[i].role=kind;
      }
   }
   unsigned frame=redfin_composition_trace.images+1;
   fprintf(stderr,"REDFIN METAL DRAW ALPHA: boot=%s frame=%u draw=%u role=%s slot=%u surface=%u samples=%u min=%u max=%u zero=%u opaque=%u premult-violations=%u zero-nonblack=%u alpha-crc32=%08x\n",
      redfin_composition_trace.boot,frame,draw,role,slot,texture->redfin_surface,w*h,min_alpha,max_alpha,
      zero_alpha,opaque,invalid_premult,zero_nonblack,alpha_crc);
   int header=snprintf(line,512,"REDFIN METAL DRAW IMAGE: boot=%s frame=%u draw=%u role=%s slot=%u surface=%u format=%u source=%ux%u width=%u height=%u raw=%zu crc32=%08x data=",
      redfin_composition_trace.boot,frame,draw,role,slot,texture->redfin_surface,texture->shape.pixel_format,
      width,height,w,h,raw,crc);
   if(header<=0||header>=512){free(rgb);free(alpha);free(line);return;}
   static const char alphabet[]="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
   size_t at=(size_t)header;
   for(size_t i=0;i<raw;i+=3) {
      uint32_t value=((uint32_t)rgb[i]<<16)|((uint32_t)rgb[i+1]<<8)|rgb[i+2];
      line[at++]=alphabet[(value>>18)&63];line[at++]=alphabet[(value>>12)&63];
      line[at++]=alphabet[(value>>6)&63];line[at++]=alphabet[value&63];
   }
   line[at++]='\n';
   if(write(STDERR_FILENO,line,at)==(ssize_t)at)++redfin_composition_trace.images;
   free(rgb);free(alpha);free(line);
}
static void
rwa_redfin_trace_buffer(const char *stage,unsigned slot,const struct rwa_buffer *buffer,size_t offset,unsigned draw)
{
   if(!buffer||!buffer->map||offset>=buffer->size)return;
   size_t bytes=MIN2(buffer->size-offset,64);const uint8_t *data=(const uint8_t *)buffer->map+offset;
   fprintf(stderr,"REDFIN METAL DRAW BUFFER: boot=%s draw=%u stage=%s slot=%u offset=%zu bytes=%zu words=",
      redfin_composition_trace.boot,draw,stage,slot,offset,bytes);
   for(unsigned i=0;i<bytes/4;++i){uint32_t word;memcpy(&word,data+4*i,4);fprintf(stderr,"%08x%s",word,i+1==bytes/4?"":",");}
   fputc('\n',stderr);
}
static void
rwa_redfin_trace_stage(struct rwa_render *render,const struct air_shader_info *info,
    const struct rwa_bindings *bindings,const struct rwa_buffer_bind *table,unsigned count,
    const char *role,unsigned draw)
{
   for(unsigned i=0;i<MIN2(count,4);++i)if(table)rwa_redfin_trace_buffer(role,i,table[i].buffer,table[i].offset,draw);
   for(unsigned i=0;i<info->num_resources;++i) {
      const struct air_resource *r=&info->resources[i];if(r->kind!=AIR_RESOURCE_TEXTURE)continue;
      struct rwa_texture *texture=NULL;
      if(r->argbuf_set!=~0u) {
         struct rwa_buffer *b=NULL;struct rwa_sampler *s=NULL;size_t offset=0;char why[128]={0};
         if(argbuf_member(r,table,count,"draw observation",&b,&offset,&texture,&s,why,sizeof(why)))continue;
      } else if(r->index<bindings->texture_count&&bindings->textures)texture=bindings->textures[r->index];
      rwa_redfin_trace_texture(texture,role,r->index,draw);
   }
   (void)render;
}
static int
rwa_redfin_trace_draw(struct rwa_render *render,const struct rwa_draw *draw,char *why,size_t why_size)
{
   if(!rwa_redfin_trace_selected()||redfin_composition_trace.draws>=256||redfin_composition_trace.images>=48)return 0;
   struct rwa_device *device=render->device;
   if(redfin_metal_scope_drain(&device->command_scope,command_scope_finish,device,why,why_size))return -1;
   unsigned number=++redfin_composition_trace.draws;
   fprintf(stderr,"REDFIN METAL DRAW: boot=%s draw=%u vertex=%s fragment=%s primitive=%u start=%u count=%u instances=%u base-instance=%u colors=%u actual-drain=1 diagnostic-timing=1\n",
      redfin_composition_trace.boot,number,render->generated_vertex?"generated":render->vinfo.entry_point,
      render->finfo.entry_point,draw->primitive,draw->vertex_start,draw->vertex_count,draw->instance_count,draw->base_instance,draw->color_count);
   for(unsigned i=0;i<MIN2(draw->vertex_stream_count,4);++i)if(draw->vertex_streams) {
      fprintf(stderr,"REDFIN METAL DRAW STREAM: draw=%u slot=%u stride=%u\n",number,i,render->vstate.stride[i]);
      rwa_redfin_trace_buffer("STREAM",i,draw->vertex_streams[i].buffer,draw->vertex_streams[i].offset,number);
   }
   if(!render->generated_vertex)rwa_redfin_trace_stage(render,&render->vinfo,&draw->vertex,
      draw->vertex_buffer_table,draw->vertex_buffer_table_count,"INPUTV",number);
   rwa_redfin_trace_stage(render,&render->finfo,&draw->fragment,draw->fragment_buffer_table,
      draw->fragment_buffer_table_count,"INPUTF",number);
   for(unsigned i=0;i<MIN2(draw->color_count,2);++i)rwa_redfin_trace_texture(draw->color[i],"OUTPUT",i,number);
   return 0;
}
