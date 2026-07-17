// Tool position pointer mesh with simple diffuse shading.
// Drawn in two passes (back faces, then front faces) for correct translucency.

---vertex
$HEADER$

attribute vec3 v_pos;
attribute vec3 v_normal;

uniform vec3 offset;
uniform mat4 rotation;

varying vec3 normal_vec;

void main()
{
    vec4 rotated = rotation * vec4(v_pos, 1.0);
    vec3 world_pos = rotated.xyz + offset;
    vec4 eye_pos = modelview_mat * vec4(world_pos, 1.0);
    // Transform normals with the same rotation + view as positions (w=0 skips translation).
    normal_vec = (modelview_mat * rotation * vec4(v_normal, 0.0)).xyz;
    tex_coord0 = vec2(0.0);
    gl_Position = projection_mat * eye_pos;
}

---fragment
$HEADER$

varying vec3 normal_vec;

void main()
{
    // abs() keeps both shell passes lit; light is fixed in view space so shading
    // stays stable while orbiting the camera.
    vec3 n = normalize(normal_vec);
    float shade = 0.35 + 0.65 * abs(dot(n, normalize(vec3(0.35, 0.55, 1.0))));
    vec3 color = vec3(0.3, 0.3, 1.0) * shade;
    gl_FragColor = vec4(color, 0.3) * texture2D(texture0, tex_coord0);
}
