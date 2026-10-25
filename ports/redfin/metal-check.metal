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
