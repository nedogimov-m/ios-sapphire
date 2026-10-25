// SPDX-License-Identifier: MIT
#include <metal_stdlib>
using namespace metal;

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
