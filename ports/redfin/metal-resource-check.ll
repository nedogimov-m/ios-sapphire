; SPDX-License-Identifier: MIT
; Authored AIR regression: actual private reference cells, conditional writes,
; alias selection, resource phis, helper arguments, initializers and dynamic lanes.
source_filename = "redfin_resource_contract"
target datalayout = "e-p:64:64:64-i1:8:8-i8:8:8-i16:16:16-i32:32:32-i64:64:64-f32:32:32-f64:64:64-v24:32:32-v48:64:64-v96:128:128-n8:16:32"
target triple = "air64-apple-ios16.0.0"

%struct._texture_2d_t = type opaque
%struct._sampler_t = type opaque
%struct.redfin_constants = type { i8, i32, [2 x <3 x i16>], float }

@redfin_constants = internal addrspace(2) constant %struct.redfin_constants {
  i8 59, i32 305419896,
  [2 x <3 x i16>] [<3 x i16> <i16 17, i16 273, i16 4369>,
                     <3 x i16> <i16 33, i16 545, i16 8737>],
  float 0x7FF82468A0000000
}, align 8
@redfin_state = internal addrspace(2) global i32 826366246, align 4
@redfin_zero = internal addrspace(2) global [2 x i8] zeroinitializer, align 1
@__air_sampler_state = internal addrspace(2) constant i64 -9188470239253757879, align 8
@redfin_fallback = internal constant { %struct._sampler_t addrspace(2)* } {
  %struct._sampler_t addrspace(2)* bitcast (i64 addrspace(2)* @__air_sampler_state to %struct._sampler_t addrspace(2)*)
}, align 8

define internal <4 x float> @redfin_sample(%struct._texture_2d_t addrspace(1)* %texture,
    %struct._sampler_t addrspace(2)* %sampler, i32 addrspace(2)* %word) noinline {
entry:
  %data = load i32, i32 addrspace(2)* %word, align 4
  %sample = call { <4 x float>, i8 } @air.sample_texture_2d.v4f32(
      %struct._texture_2d_t addrspace(1)* %texture,
      %struct._sampler_t addrspace(2)* %sampler,
      <2 x float> <float 0.5, float 0.5>, i1 true, <2 x i32> zeroinitializer,
      i1 true, float 0.0, float 0.0, i32 0)
  %color = extractvalue { <4 x float>, i8 } %sample, 0
  ; This component verifies the helper's chosen pointer and its caller-owned offset.
  %bits = bitcast i32 %data to float
  %result = insertelement <4 x float> %color, float %bits, i32 3
  ret <4 x float> %result
}

define void @redfin_resource_contract(i32 addrspace(1)* %output,
    i32 addrspace(2)* %control, %struct._texture_2d_t addrspace(1)* %texture,
    %struct._sampler_t addrspace(2)* %nearest, %struct._sampler_t addrspace(2)* %linear) {
entry:
  %cells = alloca [2 x %struct._sampler_t addrspace(2)*], align 8
  %a = getelementptr [2 x %struct._sampler_t addrspace(2)*], [2 x %struct._sampler_t addrspace(2)*]* %cells, i32 0, i32 0
  %b = getelementptr [2 x %struct._sampler_t addrspace(2)*], [2 x %struct._sampler_t addrspace(2)*]* %cells, i32 0, i32 1
  store %struct._sampler_t addrspace(2)* %nearest, %struct._sampler_t addrspace(2)** %a, align 8
  store %struct._sampler_t addrspace(2)* %linear, %struct._sampler_t addrspace(2)** %b, align 8
  %seed = load i32, i32 addrspace(2)* %control, align 4
  %odd = and i32 %seed, 1
  %choose = icmp eq i32 %odd, 0
  br i1 %choose, label %write_a, label %write_b
write_a:
  store %struct._sampler_t addrspace(2)* %linear, %struct._sampler_t addrspace(2)** %a, align 8
  br label %merged
write_b:
  store %struct._sampler_t addrspace(2)* %nearest, %struct._sampler_t addrspace(2)** %b, align 8
  br label %merged
merged:
  %cell = select i1 %choose, %struct._sampler_t addrspace(2)** %a, %struct._sampler_t addrspace(2)** %b
  %state = load %struct._sampler_t addrspace(2)*, %struct._sampler_t addrspace(2)** %cell, align 8
  %fallback_cell = getelementptr { %struct._sampler_t addrspace(2)* }, { %struct._sampler_t addrspace(2)* }* @redfin_fallback, i32 0, i32 0
  %fallback = load %struct._sampler_t addrspace(2)*, %struct._sampler_t addrspace(2)** %fallback_cell, align 8
  %use_fallback = and i32 %seed, 4
  %fallback_on = icmp ne i32 %use_fallback, 0
  %selected_state = select i1 %fallback_on, %struct._sampler_t addrspace(2)* %fallback, %struct._sampler_t addrspace(2)* %state
  %null_bit = and i32 %seed, 2
  %is_null = icmp ne i32 %null_bit, 0
  br i1 %is_null, label %null_path, label %real_path
null_path:
  %null_texture = call %struct._texture_2d_t addrspace(1)* @air.get_null_texture_2d()
  br label %joined
real_path:
  br label %joined
joined:
  %selected_texture = phi %struct._texture_2d_t addrspace(1)* [ %null_texture, %null_path ], [ %texture, %real_path ]
  %word_offset = and i32 %seed, 3
  %word = getelementptr i32, i32 addrspace(2)* %control, i32 %word_offset
  %constant_word = getelementptr %struct.redfin_constants, %struct.redfin_constants addrspace(2)* @redfin_constants, i32 0, i32 1
  %chosen_word = select i1 %fallback_on, i32 addrspace(2)* %constant_word, i32 addrspace(2)* %word
  %result = call <4 x float> @redfin_sample(%struct._texture_2d_t addrspace(1)* %selected_texture,
      %struct._sampler_t addrspace(2)* %selected_state, i32 addrspace(2)* %chosen_word)
  %bits = bitcast <4 x float> %result to <4 x i32>
  %out4 = bitcast i32 addrspace(1)* %output to <4 x i32> addrspace(1)*
  store <4 x i32> %bits, <4 x i32> addrspace(1)* %out4, align 4
  %width = call i32 @air.get_width_texture_2d(%struct._texture_2d_t addrspace(1)* %selected_texture, i32 0)
  %out_width = getelementptr i32, i32 addrspace(1)* %output, i32 4
  store i32 %width, i32 addrspace(1)* %out_width, align 4
  %state_value = load i32, i32 addrspace(2)* @redfin_state, align 4
  %zero_address = getelementptr [2 x i8], [2 x i8] addrspace(2)* @redfin_zero, i32 0, i32 1
  %zero = load i8, i8 addrspace(2)* %zero_address, align 1
  %zero32 = zext i8 %zero to i32
  %combined = xor i32 %state_value, %zero32
  %out_state = getelementptr i32, i32 addrspace(1)* %output, i32 5
  store i32 %combined, i32 addrspace(1)* %out_state, align 4
  %vector = insertelement <4 x i32> <i32 17, i32 33, i32 65, i32 129>, i32 %seed, i32 %word_offset
  %lane = extractelement <4 x i32> %vector, i32 %word_offset
  %out_lane = getelementptr i32, i32 addrspace(1)* %output, i32 6
  store i32 %lane, i32 addrspace(1)* %out_lane, align 4
  %nan_address = getelementptr %struct.redfin_constants, %struct.redfin_constants addrspace(2)* @redfin_constants, i32 0, i32 3
  %nan_bits = bitcast float addrspace(2)* %nan_address to i32 addrspace(2)*
  %nan = load i32, i32 addrspace(2)* %nan_bits, align 4
  %out_nan = getelementptr i32, i32 addrspace(1)* %output, i32 7
  store i32 %nan, i32 addrspace(1)* %out_nan, align 4
  %row = and i32 %seed, 1
  %short_address = getelementptr %struct.redfin_constants, %struct.redfin_constants addrspace(2)* @redfin_constants, i32 0, i32 2, i32 %row, i32 2
  %short_bits = bitcast i16 addrspace(2)* %short_address to i32 addrspace(2)*
  %short_word = load i32, i32 addrspace(2)* %short_bits, align 2
  %short32 = and i32 %short_word, 65535
  %out_short = getelementptr i32, i32 addrspace(1)* %output, i32 8
  store i32 %short32, i32 addrspace(1)* %out_short, align 4
  ret void
}

declare { <4 x float>, i8 } @air.sample_texture_2d.v4f32(%struct._texture_2d_t addrspace(1)*,
    %struct._sampler_t addrspace(2)*, <2 x float>, i1, <2 x i32>, i1, float, float, i32)
declare %struct._texture_2d_t addrspace(1)* @air.get_null_texture_2d()
declare i32 @air.get_width_texture_2d(%struct._texture_2d_t addrspace(1)*, i32)

!air.version = !{!0}
!air.language_version = !{!1}
!air.kernel = !{!2}
!0 = !{i32 2, i32 5, i32 0}
!1 = !{!"Metal", i32 2, i32 4, i32 0}
!2 = !{void (i32 addrspace(1)*, i32 addrspace(2)*, %struct._texture_2d_t addrspace(1)*,
    %struct._sampler_t addrspace(2)*, %struct._sampler_t addrspace(2)*)* @redfin_resource_contract, !3, !4}
!3 = !{}
!4 = !{!5, !6, !7, !8, !9}
!5 = !{i32 0, !"air.buffer", !"air.location_index", i32 0, i32 1, !"air.read_write", !"air.address_space", i32 1, !"air.buffer_size", i32 256, !"air.arg_type_name", !"uint", !"air.arg_name", !"output"}
!6 = !{i32 1, !"air.buffer", !"air.location_index", i32 1, i32 1, !"air.read", !"air.address_space", i32 2, !"air.buffer_size", i32 32, !"air.arg_type_name", !"uint", !"air.arg_name", !"control"}
!7 = !{i32 2, !"air.texture", !"air.location_index", i32 0, i32 1, !"air.sample", !"air.arg_type_name", !"texture2d<float, sample>", !"air.arg_name", !"texture"}
!8 = !{i32 3, !"air.sampler", !"air.location_index", i32 0, i32 1, !"air.arg_type_name", !"sampler", !"air.arg_name", !"nearest"}
!9 = !{i32 4, !"air.sampler", !"air.location_index", i32 1, i32 1, !"air.arg_type_name", !"sampler", !"air.arg_name", !"linear"}
