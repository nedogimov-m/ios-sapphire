// SPDX-License-Identifier: MIT
#include <metal_stdlib>
using namespace metal;

/* A bounded dependent workload keeps one raw-buffer submission on the GPU
 * long enough for the second real publication to be observed. The iteration
 * count is a runtime uniform, so shader preparation does not unroll it. */
kernel void redfin_physical_pending(device uint *output [[buffer(0)]],
    constant uint2 &parameters [[buffer(1)]],uint index [[thread_position_in_grid]])
{
    uint value=index^parameters.x;
    for(uint i=0;i<parameters.y;++i)value=value*1664525u+1013904223u;
    output[index]=value;
}

kernel void redfin_ubo_fixed(device uint *output [[buffer(0)]],
    constant uint &first [[buffer(1)]],uint index [[thread_position_in_grid]])
{
    constant uint *values=&first;
    output[index]=values[13]+values[0]*17u+index;
}
kernel void redfin_ubo_dynamic(device uint *output [[buffer(0)]],
    constant uint &first [[buffer(1)]],uint index [[thread_position_in_grid]])
{
    constant uint *values=&first;
    output[index]=values[index+33]+values[0]*17u+index;
}
kernel void redfin_ubo_masked(device uint *output [[buffer(0)]],
    constant uint &first [[buffer(1)]],uint index [[thread_position_in_grid]])
{
    constant uint *values=&first;
    output[index]=values[(index&31u)+33u]+values[0]*17u+index;
}
kernel void redfin_ubo_clamped(device uint *output [[buffer(0)]],
    constant uint &first [[buffer(1)]],uint index [[thread_position_in_grid]])
{
    constant uint *values=&first;
    output[index]=values[min(index,15u)+33u]+values[0]*17u+index;
}
struct RedfinUBOArguments {
    constant uint *values [[id(0)]];
    device uint *output [[id(1)]];
};
kernel void redfin_ubo_argument_fixed(constant RedfinUBOArguments &args [[buffer(0)]],
    uint index [[thread_position_in_grid]])
{ args.output[index]=args.values[13]+args.values[0]*17u+index; }
kernel void redfin_ubo_argument_dynamic(constant RedfinUBOArguments &args [[buffer(0)]],
    uint index [[thread_position_in_grid]])
{ args.output[index]=args.values[index+33]+args.values[0]*17u+index; }
kernel void redfin_ubo_argument_masked(constant RedfinUBOArguments &args [[buffer(0)]],
    uint index [[thread_position_in_grid]])
{ args.output[index]=args.values[(index&31u)+33u]+args.values[0]*17u+index; }
kernel void redfin_ubo_argument_clamped(constant RedfinUBOArguments &args [[buffer(0)]],
    uint index [[thread_position_in_grid]])
{ args.output[index]=args.values[min(index,15u)+33u]+args.values[0]*17u+index; }
vertex float4 redfin_ubo_vertex(uint index [[vertex_id]],constant float &first [[buffer(1)]])
{
    constant float *values=&first;
    constexpr float2 positions[3]={float2(-1,-1),float2(3,-1),float2(-1,3)};
    return float4(positions[index]*float2(values[0],values[13]),0,1);
}
fragment float4 redfin_ubo_fragment(constant float &first [[buffer(1)]])
{
    constant float *values=&first;
    return float4(values[0],values[5],values[9],values[13]);
}
vertex float4 redfin_ubo_dynamic_vertex(uint index [[vertex_id]],constant float &first [[buffer(1)]])
{
    constant float *values=&first;
    constexpr float2 positions[3]={float2(-1,-1),float2(3,-1),float2(-1,3)};
    return float4(positions[index]*float2(values[0],values[index+33]),0,1);
}
fragment float4 redfin_ubo_dynamic_fragment(float4 position [[position]],constant float &first [[buffer(1)]])
{
    constant float *values=&first;
    return float4(values[uint(position.x)+33],values[0],values[5],values[9]);
}

kernel void redfin_affine(device uint *output [[buffer(0)]],
                          constant uint &seed [[buffer(1)]],
                          uint index [[thread_position_in_grid]])
{
    output[index]=(index^seed)*1664525u+1013904223u;
}
struct RedfinVertex {float4 position [[position]];};
vertex RedfinVertex redfin_vertex(uint index [[vertex_id]])
{
    const float2 positions[3]={float2(-1,-1),float2(3,-1),float2(-1,3)};
    RedfinVertex result;result.position=float4(positions[index],0,1);return result;
}
fragment float4 redfin_fragment()
{ return float4(0.25,0.5,0.75,1); }
fragment float4 redfin_batch_fragment(constant float4 &color [[buffer(0)]])
{ return color; }
fragment float4 redfin_dependency_fragment(texture2d<float,access::read> source [[texture(0)]])
{ return source.read(uint2(0,0)); }

struct RedfinMRT {float4 first [[color(0)]];float4 second [[color(1)]];};
fragment RedfinMRT redfin_mrt_fragment()
{ RedfinMRT value;value.first=float4(1);value.second=float4(1,1,0,1);return value; }
fragment float4 redfin_fetch_other_fragment(float4 other [[color(1)]])
{ return other; }
fragment float4 redfin_position_sample_fragment(float4 position [[position]],
    texture2d<float,access::read> source [[texture(0)]])
{ return source.read(uint2(position.xy)); }

fragment float4 redfin_alpha_sample_fragment(float4 position [[position]],
    texture2d<float,access::read> source [[texture(0)]])
{
    float4 value=source.read(uint2(position.xy));
    return float4(value.a,value.r,value.g+value.b,1);
}

struct RedfinStreamInput {
    float2 position [[attribute(0)]];
    float2 uv [[attribute(1)]];
    float4 tint [[attribute(2)]];
    float mask [[attribute(3)]];
};
struct RedfinStreamOutput {
    float4 position [[position]];
    float2 uv [[user(locn0)]];
    float4 tint [[user(locn1)]];
    float mask [[user(locn2)]];
};
vertex RedfinStreamOutput redfin_stream_vertex(RedfinStreamInput input [[stage_in]])
{
    RedfinStreamOutput value;value.position=float4(input.position,0,1);
    value.uv=input.uv;value.tint=input.tint;value.mask=input.mask;return value;
}
fragment float4 redfin_stream_fragment(RedfinStreamOutput input [[stage_in]],
    texture2d<float> source [[texture(0)]],sampler state [[sampler(0)]])
{ return source.sample(state,input.uv)*input.tint*input.mask; }

// Real half arithmetic/storage with full-register transport between stages.
// Separate MRT and constant-only paths distinguish varying transport from
// native half colour export and packed UBO loads.
fragment half4 redfin_half_constant()
{ return half4(0.125h,0.375h,0.625h,0.875h); }

struct RedfinHalfPacking {half3 vector;half scalar;packed_half3 packed;half tail;};
fragment half4 redfin_half_uniform(constant RedfinHalfPacking &value [[buffer(1)]])
{ return half4(value.vector.x,value.scalar,value.packed.z,value.tail); }

struct RedfinHalfMRT {half4 first [[color(0)]];half4 second [[color(1)]];};
fragment RedfinHalfMRT redfin_half_mrt(constant half4 &color [[buffer(1)]])
{ RedfinHalfMRT out;out.first=color;out.second=color.zyxw;return out; }
fragment half4 redfin_half_fetch(half4 other [[color(1)]],constant half4 &scale [[buffer(1)]])
{ return other*scale; }

struct RedfinHalfInput {
    float2 position [[attribute(0)]];
    half2 uv [[attribute(1)]];
    half4 tint [[attribute(2)]];
    half4 flatTint [[attribute(3)]];
    half mask [[attribute(4)]];
};
struct RedfinHalfOutput {
    float4 position [[position]];
    half2 uv [[user(locn0)]];
    half4 tint [[user(locn1)]];
    half4 flatTint [[user(locn2),flat]];
    half mask [[user(locn3),center_no_perspective]];
};
vertex RedfinHalfOutput redfin_half_vertex(RedfinHalfInput input [[stage_in]])
{
    RedfinHalfOutput out;out.position=float4(input.position,0,1);out.uv=input.uv;
    out.tint=input.tint;out.flatTint=input.flatTint;out.mask=input.mask;return out;
}
fragment half4 redfin_half_stream_fragment(RedfinHalfOutput input [[stage_in]],
    texture2d<half> source [[texture(0)]],sampler state [[sampler(0)]])
{ return source.sample(state,float2(input.uv))*input.tint*input.flatTint*input.mask; }

constant uint redfin_fc_seed [[function_constant(37)]];
constant float4 redfin_fc_vector [[function_constant(41)]];
constant uchar3 redfin_fc_opcodes [[function_constant(58)]];
constant uint redfin_fc_optional [[function_constant(59)]];
struct redfin_fc_arguments {device uint *output [[id(0)]];};
kernel void redfin_constants(constant redfin_fc_arguments &arguments [[buffer(0)]],uint id [[thread_position_in_grid]])
{
    if(id>=16)return;
    uint option=is_function_constant_defined(redfin_fc_optional)?redfin_fc_optional+0x4321u:0x1234u;
    uint packed=uint(redfin_fc_opcodes.x)|(uint(redfin_fc_opcodes.y)<<8)|(uint(redfin_fc_opcodes.z)<<16);
    arguments.output[id]=redfin_fc_seed^as_type<uint>(redfin_fc_vector[id&3])^packed^option^(id*1664525u);
}
vertex float4 redfin_constants_vertex(uint id [[vertex_id]])
{
    constexpr float2 points[6]={float2(-1,-1),float2(1,-1),float2(-1,1),float2(-1,1),float2(1,-1),float2(1,1)};
    return float4(points[id]*redfin_fc_vector.xy,0,1);
}
fragment float4 redfin_constants_fragment() {return redfin_fc_vector;}

constant bool redfin_fc_flag [[function_constant(70)]];
constant bool3 redfin_fc_flags [[function_constant(72)]];
kernel void redfin_bool_constants(device uint *output [[buffer(0)]],
    constant uint &seed [[buffer(1)]], uint index [[thread_position_in_grid]])
{
    if(index>=16)return;
    uint flags=uint(redfin_fc_flag)|(uint(redfin_fc_flags.x)<<8)|
        (uint(redfin_fc_flags.y)<<16)|(uint(redfin_fc_flags.z)<<24);
    output[index]=(seed+index*1664525u)^flags;
}
