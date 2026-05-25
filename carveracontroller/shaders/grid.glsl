// XY reference grid shader

---vertex
$HEADER$
attribute vec3 position;
attribute vec3 color_att;

uniform mat4 center_offset;
uniform mat4 view_mat;
uniform mat4 proj_mat;

varying vec3 vs_color;

void main()
{
    vs_color = color_att;
    tex_coord0 = vec2(0.0);
    gl_Position = proj_mat * view_mat * center_offset * vec4(position, 1.0);
}

---fragment
$HEADER$

varying vec3 vs_color;

void main()
{
    gl_FragColor = vec4(vs_color, 1.0) * texture2D(texture0, tex_coord0);
}
