// Orientation view cube — same view_mat as toolpath & grid, anchored at the orbit origin.

---vertex
$HEADER$

attribute vec3 v_pos;
attribute vec3 v_normal;
attribute vec2 v_tc0;

uniform mat4 view_mat;
uniform mat4 proj_mat;
uniform float cube_scale;

varying vec4 normal_vec;

void main()
{
    vec3 local_pos = v_pos * cube_scale;
    normal_vec = view_mat * vec4(v_normal, 0.0);
    tex_coord0 = v_tc0;
    gl_Position = proj_mat * view_mat * vec4(local_pos, 1.0);
}

---fragment
$HEADER$

varying vec4 normal_vec;

void main()
{
    float shade = 0.55 + 0.45 * abs(dot(normalize(normal_vec.xyz), vec3(0.35, 0.55, 1.0)));
    vec4 tex = texture2D(texture0, tex_coord0);
    gl_FragColor = vec4(tex.rgb * shade, tex.a);
}
