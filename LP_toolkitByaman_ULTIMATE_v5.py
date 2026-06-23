bl_info = {
    "name": "LP Toolkit by Aman - ULTIMATE",
    "author": "Aman",
    "version": (5, 0, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > LP Toolkit (N Panel)",
    "description": "ULTIMATE v5: Labels, Asset Library, Quick Shortcuts, Spell Check, Photoshop/Substance Integration, Timeline Markers, Performance Monitor, 3D Viewer IPR",
    "category": "3D View",
    "support": "COMMUNITY",
    "doc_url": "https://github.com/Amank12721/UnifiedToolkit",
    "tracker_url": "https://github.com/Amank12721/UnifiedToolkit/issues",
    "update_url": "https://raw.githubusercontent.com/Amank12721/UnifiedToolkit/main/version.json"
}

import bpy
import os
import pathlib
import re
import platform
import subprocess
from mathutils import Vector
import bpy.props
import blf
import bpy_extras
from bpy.app import version as blender_version
from difflib import SequenceMatcher
import json
from collections import defaultdict, deque
import urllib.request
from urllib.error import URLError
import time
from bpy_extras.io_utils import ImportHelper
import datetime
import urllib.parse
# 3D Viewer IPR imports
import webbrowser
import http.server
import threading
import socketserver
import tempfile
import shutil

# ============= TEXTURE TYPE DETECTION (for Photoshop Integration) =============
TEXTURE_PATTERNS = {
    'base_color': ['basecolor', 'diffuse', 'albedo', 'color', '_col', '_bc', '_diff'],
    'metallic': ['metallic', 'metal', '_met', '_m'],
    'roughness': ['roughness', 'rough', '_rough', '_r'],
    'normal': ['normal', 'norm', '_n', '_nrm'],
    'height': ['height', 'displacement', 'disp', '_h', '_disp'],
    'ambient_occlusion': ['ao', 'ambient', 'occlusion', '_ao'],
    'emission': ['emission', 'emissive', 'emit', '_e'],
    'alpha': ['alpha', 'opacity', 'transparent', '_a'],
}

def detect_texture_type(filename):
    """Smart detection of texture type from filename"""
    filename_lower = filename.lower()
    for tex_type, patterns in TEXTURE_PATTERNS.items():
        for pattern in patterns:
            if pattern in filename_lower:
                return tex_type
    return None

def get_material_output_node(material):
    """Get or create material output node"""
    if not material.use_nodes:
        material.use_nodes = True
    nodes = material.node_tree.nodes
    for node in nodes:
        if node.type == 'OUTPUT_MATERIAL':
            return node
    output = nodes.new('ShaderNodeOutputMaterial')
    output.location = (300, 0)
    return output

def get_or_create_principled_bsdf(material):
    """Get or create Principled BSDF node"""
    nodes = material.node_tree.nodes
    for node in nodes:
        if node.type == 'BSDF_PRINCIPLED':
            return node
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.location = (0, 0)
    output = get_material_output_node(material)
    material.node_tree.links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
    return bsdf

# ============= GLOBAL VARIABLES =============
_temporary_display_end_time = 0
TEMPORARY_DISPLAY_DURATION = 3.0
_last_update_check = 0
_update_check_interval = 3600
_cached_update_info = (None, None)
_draw_handlers = []

# 3D Viewer IPR server state
ipr_server_state = {'server': None, 'thread': None, 'port': None, 'temp_dir': None}

# ============= PERFORMANCE MONITORING =============
class PerformanceMonitor:
    def __init__(self, max_samples=60):
        self.fps_samples = deque(maxlen=max_samples)
        self.operation_times = {}
        self.last_time = time.time()
        self.frame_count = 0
        self.is_monitoring = False
        self.max_samples = max_samples

    def start_operation(self, operation_name):
        if not self.is_monitoring:
            return
        self.operation_times[operation_name] = time.time()

    def end_operation(self, operation_name):
        if not self.is_monitoring:
            return
        if operation_name in self.operation_times:
            duration = time.time() - self.operation_times[operation_name]
            if not isinstance(self.operation_times[operation_name], deque):
                self.operation_times[operation_name] = deque(maxlen=self.max_samples)
            self.operation_times[operation_name].append(duration)

    def update_fps(self):
        if not self.is_monitoring:
            return
        current_time = time.time()
        self.frame_count += 1
        
        if current_time - self.last_time >= 1.0:
            fps = self.frame_count / (current_time - self.last_time)
            self.fps_samples.append(fps)
            self.frame_count = 0
            self.last_time = current_time

    def get_average_fps(self):
        if not self.fps_samples:
            return 0
        return sum(self.fps_samples) / len(self.fps_samples)

    def get_operation_stats(self):
        stats = {}
        for op_name, times in self.operation_times.items():
            if isinstance(times, deque) and times:
                stats[op_name] = {
                    'avg': sum(times) / len(times),
                    'min': min(times),
                    'max': max(times)
                }
        return stats

performance_monitor = PerformanceMonitor()

def draw_performance_stats(context):
    if not context.scene.show_performance_stats:
        return

    performance_monitor.update_fps()

    font_id = 0
    blf.size(font_id, 12)
    blf.color(font_id, 1.0, 1.0, 1.0, 1.0)

    region = context.region
    if not region:
        return

    fps = performance_monitor.get_average_fps()
    blf.position(font_id, 10, region.height - 20, 0)
    blf.draw(font_id, f"FPS: {fps:.1f}")

    stats = performance_monitor.get_operation_stats()
    y_pos = region.height - 40
    for op_name, op_stats in stats.items():
        text = f"{op_name}: {op_stats['avg']*1000:.1f}ms"
        blf.position(font_id, 10, y_pos, 0)
        blf.draw(font_id, text)
        y_pos -= 20

def check_for_update():
    global _last_update_check, _cached_update_info
    
    current_time = time.time()
    
    if current_time - _last_update_check < _update_check_interval:
        return _cached_update_info
        
    try:
        if not bl_info.get('update_url'):
            return None, None
            
        with urllib.request.urlopen(bl_info['update_url'], timeout=5) as response:
            data = json.loads(response.read())
            latest_version = tuple(data.get('version', [0, 0]))
            download_url = data.get('download_url', '')
            
            _last_update_check = current_time
            _cached_update_info = (latest_version, download_url)
            
            if latest_version > bl_info['version']:
                return latest_version, download_url
    except (URLError, json.JSONDecodeError, Exception):
        return _cached_update_info
    return None, None

# ============= DESCRIPTION SUGGESTER =============
class DescriptionSuggester:
    def __init__(self):
        self.word_frequencies = defaultdict(int)
        self.common_mistakes = defaultdict(list)
        self.load_data()
        self.add_default_science_words()
    
    def add_default_science_words(self):
        try:
            script_dir = os.path.dirname(__file__)
            science_words_path = os.path.join(script_dir, "wordlist.json")
            if os.path.exists(science_words_path):
                with open(science_words_path, 'r', encoding='utf-8') as f:
                    science_words = json.load(f)
                for word in science_words:
                    self.add_description(word)
        except Exception as e:
            print(f"Error loading default science words: {e}")
    
    def load_data(self):
        try:
            if os.path.exists("description_data.json"):
                with open("description_data.json", 'r') as f:
                    data = json.load(f)
                    self.word_frequencies = defaultdict(int, data.get('frequencies', {}))
                    self.common_mistakes = defaultdict(list, data.get('mistakes', {}))
        except Exception as e:
            print(f"Error loading description data: {e}")
    
    def save_data(self):
        try:
            data = {
                'frequencies': dict(self.word_frequencies),
                'mistakes': dict(self.common_mistakes)
            }
            with open("description_data.json", 'w') as f:
                json.dump(data, f)
        except Exception as e:
            print(f"Error saving description data: {e}")
    
    def add_description(self, description):
        words = description.lower().split()
        for word in words:
            self.word_frequencies[word] += 1
    
    def get_similarity(self, word1, word2):
        return SequenceMatcher(None, word1.lower(), word2.lower()).ratio()
    
    def find_similar_words(self, word, threshold=0.8):
        similar_words = []
        for known_word in self.word_frequencies.keys():
            if self.get_similarity(word, known_word) > threshold:
                similar_words.append((known_word, self.word_frequencies[known_word]))
        return sorted(similar_words, key=lambda x: x[1], reverse=True)
    
    def check_description(self, description):
        words = description.lower().split()
        suggestions = []
        
        for word in words:
            if len(word) <= 2:
                continue
                
            if word not in self.word_frequencies:
                similar_words = self.find_similar_words(word)
                if similar_words:
                    suggestions.append({
                        'word': word,
                        'suggestions': [w[0] for w in similar_words[:3]]
                    })
        
        return suggestions

description_suggester = DescriptionSuggester()

# ============= SPELL CHECKING =============
def get_spell_cache(scene):
    try:
        cache = json.loads(scene.spelling_spotter_cache_json)
        if not isinstance(cache, dict):
            raise ValueError
        if "results" not in cache or "timestamp" not in cache:
            raise ValueError
        return cache
    except Exception:
        return {"results": {}, "timestamp": None}

def set_spell_cache(scene, results):
    cache = {
        "results": results,
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S')
    }
    scene.spelling_spotter_cache_json = json.dumps(cache)

def check_spelling_languagetool(text):
    url = "https://api.languagetool.org/v2/check"
    data = urllib.parse.urlencode({
        "text": text,
        "language": "en-US"
    }).encode()
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req) as response:
        result = json.loads(response.read().decode())
    errors = []
    for match in result.get("matches", []):
        word = text[match["offset"]:match["offset"]+match["length"]]
        suggestions = [r["value"] for r in match.get("replacements", [])]
        errors.append((word, suggestions))
    stripped = text.lstrip()
    if stripped and stripped[0].islower():
        errors.append((stripped.split()[0], ["Description starts with lowercase letter"]))
    return errors

# ============= UTILITY FUNCTIONS =============
def create_transparent_material(name):
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Alpha"].default_value = 0.0
        bsdf.inputs["Base Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    
    mat.blend_method = 'BLEND'
    mat.use_backface_culling = False
    
    return mat

def get_next_label_number():
    max_num = 0
    for obj in bpy.data.objects:
        if obj.name.startswith("dot-") or obj.name.startswith("label-"):
            try:
                num = int(obj.name.split("-")[-1])
                max_num = max(max_num, num)
            except ValueError:
                continue
    return max_num + 1

def rename_objects(selected_only=False):
    objects = bpy.context.selected_objects if selected_only else bpy.data.objects
    for i, obj in enumerate(objects, start=1):
        if obj.name.startswith("lbl.") or "NS" in obj.name or "ND" in obj.name or "NR" in obj.name:
            continue
        if not obj.name.startswith("mesh-") and not obj.name.startswith("dot."):
            obj.name = f"mesh-{i:02}"

def rename_materials(selected_only=False):
    materials = set()
    if selected_only:
        for obj in bpy.context.selected_objects:
            for slot in obj.material_slots:
                if slot.material:
                    materials.add(slot.material)
    else:
        materials = bpy.data.materials

    for i, mat in enumerate(materials, start=1):
        if mat.name.startswith("lbl.") or "NS" in mat.name or "ND" in mat.name or "NR" in mat.name:
            continue
        if not mat.name.startswith("mat-"):
            mat.name = f"mat-{i:02}"

def resize_textures_in_selected_objects(resolution=(1024, 1024)):
    for obj in bpy.context.selected_objects:
        for slot in obj.material_slots:
            mat = slot.material
            if mat and mat.use_nodes:
                for node in mat.node_tree.nodes:
                    if node.type == 'TEX_IMAGE' and node.image:
                        if node.image.size[0] != resolution[0] or node.image.size[1] != resolution[1]:
                            node.image.scale(resolution[0], resolution[1])

# ============= PROPERTY GROUPS =============
class GLBFileResult(bpy.types.PropertyGroup):
    file_path: bpy.props.StringProperty(name="File Path")

class UnifiedToolkitPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__
    
    # Photoshop Integration Settings
    texture_export_dir: bpy.props.StringProperty(
        name="Texture Export Directory",
        description="Where UV layouts and reference images are exported (Photoshop workflow)",
        default=os.path.join(os.path.expanduser("~"), "Documents", "BlenderTextures", "Export"),
        subtype='DIR_PATH'
    )
    
    texture_import_dir: bpy.props.StringProperty(
        name="Texture Import Directory",
        description="Where painted textures are imported from (Photoshop workflow)",
        default=os.path.join(os.path.expanduser("~"), "Documents", "BlenderTextures", "Import"),
        subtype='DIR_PATH'
    )
    
    photoshop_path: bpy.props.StringProperty(
        name="Photoshop Executable",
        description="Path to Adobe Photoshop executable",
        default="C:\\Program Files\\Adobe\\Adobe Photoshop 2024\\Photoshop.exe",
        subtype='FILE_PATH'
    )
    
    use_gpu_render: bpy.props.BoolProperty(
        name="Use GPU for Render Reference",
        description="Use GPU acceleration for render reference export (faster)",
        default=True
    )
    
    supported_formats: bpy.props.StringProperty(
        name="Supported Texture Formats",
        description="Comma-separated list of texture formats",
        default="png,jpg,jpeg,tiff,tif,exr,psd"
    )
    
    # Substance Painter Integration Settings
    substance_export_dir: bpy.props.StringProperty(
        name="Substance Export Directory",
        description="Directory where GLB files are exported for Substance Painter",
        default=os.path.join(os.path.expanduser("~"), "Documents", "Adobe", "Adobe Substance 3D Painter", "export", "LIVE_LINK_AMAN"),
        subtype='DIR_PATH'
    )
    
    substance_import_dir: bpy.props.StringProperty(
        name="Substance Import Directory",
        description="Directory where Substance Painter exports textured models",
        default=os.path.join(os.path.expanduser("~"), "Documents", "Adobe", "Adobe Substance 3D Painter", "export", "LIVE_LINK_AMAN", "Subsdata"),
        subtype='DIR_PATH'
    )
    
    substance_painter_path: bpy.props.StringProperty(
        name="Substance Painter Executable",
        description="Path to Substance Painter executable",
        default="C:\\Program Files\\Adobe\\Adobe Substance 3D Painter\\Adobe Substance 3D Painter.exe",
        subtype='FILE_PATH'
    )
    
    substance_export_filename: bpy.props.StringProperty(
        name="Substance Export Filename",
        description="Name of the exported GLB file for Substance Painter",
        default="temp_model_unsub.glb"
    )
    
    # 3D Viewer IPR Settings
    viewer_html_path: bpy.props.StringProperty(
        name="Viewer HTML Path",
        description="Path to index.html viewer for IPR (saved globally)",
        default="",
        subtype='FILE_PATH'
    )

    def draw(self, context):
        layout = self.layout

        # Update Settings
        box = layout.box()
        box.label(text="Update Settings", icon='PREFERENCES')
        
        latest_version, download_url = check_for_update()
        if latest_version and latest_version > bl_info['version']:
            version_str = '.'.join(str(v) for v in latest_version)
            box.label(text=f"New version {version_str} available!", icon='INFO')
            if download_url:
                box.operator("wm.url_open", text="Download Update").url = download_url
        else:
            box.label(text="You are running the latest version.", icon='CHECKMARK')
        
        box.operator("unified.check_for_updates", text="Check for Updates Now")
        
        # Photoshop Integration Settings
        box = layout.box()
        box.label(text="Photoshop Integration:", icon='IMAGE_DATA')
        box.prop(self, "texture_export_dir")
        box.prop(self, "texture_import_dir")
        box.prop(self, "photoshop_path")
        box.prop(self, "supported_formats")
        
        # Render Settings for Photoshop
        box = layout.box()
        box.label(text="Render Reference Settings:", icon='SHADING_RENDERED')
        box.prop(self, "use_gpu_render")
        
        # Show GPU info if available
        if 'cycles' in context.preferences.addons:
            cycles_prefs = context.preferences.addons['cycles'].preferences
            compute_device_type = cycles_prefs.compute_device_type
            if compute_device_type != 'NONE':
                devices = cycles_prefs.get_devices_for_type(compute_device_type)
                gpu_names = [d.name for d in devices if d.type != 'CPU']
                if gpu_names:
                    box.label(text=f"GPU Detected: {compute_device_type}", icon='LAYER_ACTIVE')
                    for gpu_name in gpu_names[:2]:  # Show first 2 GPUs
                        box.label(text=f"  • {gpu_name}")
                else:
                    box.label(text="No GPU detected - will use CPU", icon='INFO')
            else:
                box.label(text="Configure GPU in Preferences > System", icon='INFO')
        
        # Substance Painter Integration Settings
        box = layout.box()
        box.label(text="Substance Painter Integration:", icon='FILE_TICK')
        box.prop(self, "substance_export_dir")
        box.prop(self, "substance_import_dir")
        box.prop(self, "substance_painter_path")
        box.prop(self, "substance_export_filename")
        
        # 3D Viewer IPR Settings
        box = layout.box()
        box.label(text="3D Viewer IPR Settings:", icon='VIEW_CAMERA')
        box.prop(self, "viewer_html_path")
        if self.viewer_html_path:
            viewer_path = os.path.normpath(os.path.expanduser(self.viewer_html_path))
            if os.path.isfile(viewer_path):
                box.label(text="✅ Path is valid", icon='CHECKMARK')
            else:
                box.label(text="⚠ File not found", icon='ERROR')
        else:
            box.label(text="ℹ️ Set path to enable IPR preview", icon='INFO')
        
        # Validation warnings
        if not os.path.exists(self.photoshop_path):
            layout.label(text="⚠ Photoshop executable not found!", icon='ERROR')
        if not os.path.exists(self.substance_painter_path):
            layout.label(text="⚠ Substance Painter executable not found!", icon='ERROR')

# ============= LABEL OPERATORS =============
class UNIFIED_OT_create_label(bpy.types.Operator):
    bl_idname = "unified.create_label"
    bl_label = "Create New Label"
    bl_description = "Creates a new dot label at 3D cursor or replaces selected object"

    label_object_name: bpy.props.StringProperty(name="Label Object Name", default="")
    label_mesh_name: bpy.props.StringProperty(name="Label Mesh Name", default="")
    dot_object_name: bpy.props.StringProperty(name="Dot Object Name", default="")
    dot_mesh_name: bpy.props.StringProperty(name="Dot Mesh Name", default="")
    description: bpy.props.StringProperty(name="Description", default="")
    animdata: bpy.props.StringProperty(name="Animation Data", default="")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        try:
            bpy.ops.mesh.primitive_cube_add(size=0.01)
            base_cube = bpy.context.object
            base_cube.data.name = self.label_mesh_name or "Cube.label.mesh"
            cube_mesh = base_cube.data.copy()
            bpy.data.objects.remove(base_cube)

            bpy.ops.mesh.primitive_ico_sphere_add(radius=0.01, subdivisions=1)
            base_cone = bpy.context.object
            base_cone.data.name = self.dot_mesh_name or "Icosphere.dot.mesh"
            cone_mesh = base_cone.data.copy()
            bpy.data.objects.remove(base_cone)

            transparent_mat = create_transparent_material("mat-labelmat")

            loc = context.scene.cursor.location.copy()
            rot = (0, 0, 0)
            label_obj_name = self.label_object_name
            dot_obj_name = self.dot_object_name

            if context.selected_objects:
                obj = context.selected_objects[0]
                loc = obj.location.copy()
                rot = obj.rotation_euler.copy()
                if not label_obj_name or not dot_obj_name:
                    match = re.search(r"dot\.(\d+)", obj.name)
                    if match:
                        num = match.group(1)
                        if not label_obj_name:
                            label_obj_name = f"label-{num.zfill(3)}"
                        if not dot_obj_name:
                            dot_obj_name = f"dot-{num.zfill(3)}"
                    else:
                        if not label_obj_name:
                            label_obj_name = f"label-{str(get_next_label_number()).zfill(3)}"
                        if not dot_obj_name:
                            dot_obj_name = f"dot-{str(get_next_label_number()).zfill(3)}"
                bpy.data.objects.remove(obj, do_unlink=True)
            else:
                if not label_obj_name:
                    label_obj_name = f"label-{str(get_next_label_number()).zfill(3)}"
                if not dot_obj_name:
                    dot_obj_name = f"dot-{str(get_next_label_number()).zfill(3)}"

            label_obj = bpy.data.objects.new(label_obj_name, cube_mesh)
            label_obj.location = loc
            label_obj.rotation_euler = rot
            label_obj.scale = (0.01, 0.01, 0.01)
            context.collection.objects.link(label_obj)
            label_obj.data.materials.append(transparent_mat)
            label_obj.display_type = 'WIRE'
            label_obj.show_all_edges = True
            label_obj.show_wire = True
            label_obj.show_name = True
            if self.description or self.animdata:
                label_obj["dot_label_data"] = {
                    "description": self.description,
                    "animdata": self.animdata
                }

            dot_obj = bpy.data.objects.new(dot_obj_name, cone_mesh)
            dot_obj.location = loc
            dot_obj.rotation_euler = rot
            dot_obj.scale = (0.01, 0.01, 0.01)
            context.collection.objects.link(dot_obj)
            dot_obj.data.materials.append(transparent_mat)
            dot_obj.show_name = True
            if self.description or self.animdata:
                dot_obj["dot_label_data"] = {
                    "description": self.description,
                    "animdata": self.animdata
                }

            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Error creating label: {str(e)}")
            return {'CANCELLED'}

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "label_object_name")
        layout.prop(self, "label_mesh_name")
        layout.prop(self, "dot_object_name")
        layout.prop(self, "dot_mesh_name")
        layout.prop(self, "description")
        layout.prop(self, "animdata")

class UNIFIED_OT_quick_create_label(bpy.types.Operator):
    bl_idname = "unified.quick_create_label"
    bl_label = "Quick Create Label"
    bl_description = "Quickly creates a new dot label (Ctrl+Shift+Q)"
    
    description: bpy.props.StringProperty(name="Description", default="")
    animdata: bpy.props.StringProperty(name="Animation Data", default="")
    
    _current_suggestions = []
    _last_marker_range = None
    _last_marker_names = (None, None)
    
    def invoke(self, context, event):
        scene = context.scene
        markers = sorted(scene.timeline_markers, key=lambda m: m.frame)
        if len(markers) >= 2:
            start = markers[-2].frame
            end = markers[-1].frame
            self._last_marker_range = f"{start}-{end}"
            self._last_marker_names = (markers[-2].name, markers[-1].name)
            self.animdata = self._last_marker_range
        return context.window_manager.invoke_props_dialog(self)
    
    def execute(self, context):
        try:
            if context.selected_objects:
                obj = context.selected_objects[0]
                loc = obj.location.copy()
                rot = obj.rotation_euler.copy()
            else:
                loc = context.scene.cursor.location.copy()
                rot = (0, 0, 0)
            
            num = get_next_label_number()
            label_name = f"label-{str(num).zfill(3)}"
            dot_name = f"dot-{str(num).zfill(3)}"
            
            bpy.ops.mesh.primitive_cube_add(size=0.01)
            base_cube = bpy.context.object
            base_cube.data.name = "Cube.label.mesh"
            cube_mesh = base_cube.data.copy()
            bpy.data.objects.remove(base_cube)
            
            bpy.ops.mesh.primitive_ico_sphere_add(radius=0.01, subdivisions=1)
            base_sphere = bpy.context.object
            base_sphere.data.name = "Icosphere.dot.mesh"
            sphere_mesh = base_sphere.data.copy()
            bpy.data.objects.remove(base_sphere)
            
            transparent_mat = create_transparent_material("mat-labelmat")
            
            label_obj = bpy.data.objects.new(label_name, cube_mesh)
            label_obj.location = loc
            label_obj.rotation_euler = rot
            label_obj.scale = (0.01, 0.01, 0.01)
            context.collection.objects.link(label_obj)
            label_obj.data.materials.append(transparent_mat)
            label_obj.display_type = 'WIRE'
            label_obj.show_all_edges = True
            label_obj.show_wire = True
            label_obj.show_name = True
            
            if self.description or self.animdata:
                label_obj["dot_label_data"] = {
                    "description": self.description,
                    "animdata": self.animdata
                }
                if self.description:
                    description_suggester.add_description(self.description)
                    description_suggester.save_data()
            
            dot_obj = bpy.data.objects.new(dot_name, sphere_mesh)
            dot_obj.location = loc
            dot_obj.rotation_euler = rot
            dot_obj.scale = (0.01, 0.01, 0.01)
            context.collection.objects.link(dot_obj)
            dot_obj.data.materials.append(transparent_mat)
            dot_obj.show_name = True
            
            if self.description or self.animdata:
                dot_obj["dot_label_data"] = {
                    "description": self.description,
                    "animdata": self.animdata
                }
            
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Error creating quick label: {str(e)}")
            return {'CANCELLED'}
    
    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.label(text="Description:")
        row = box.row()
        row.prop(self, "description", text="")
        if self.description:
            self._current_suggestions = description_suggester.check_description(self.description)
            if self._current_suggestions:
                box.label(text="Suggestions:")
                for suggestion in self._current_suggestions:
                    row = box.row()
                    row.label(text=f"'{suggestion['word']}' → {', '.join(suggestion['suggestions'])}")
        box = layout.box()
        box.label(text="Animation Data:")
        row = box.row()
        row.prop(self, "animdata", text="")
        if self._last_marker_range:
            box.label(text="Last Marker Range:")
            row = box.row()
            start_name, end_name = self._last_marker_names
            label_text = f"{start_name} → {end_name}: {self._last_marker_range}" if start_name and end_name else self._last_marker_range
            row.label(text=label_text)

class UNIFIED_OT_import_data(bpy.types.Operator, ImportHelper):
    bl_idname = "unified.import_data"
    bl_label = "Import Label Data (JSON)"
    bl_description = "Import dot labels from a JSON file"
    
    filename_ext = ".json"
    filter_glob: bpy.props.StringProperty(default="*.json", options={'HIDDEN'}, maxlen=255)
    
    def execute(self, context):
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to read JSON file: {e}")
            return {'CANCELLED'}

        if not isinstance(json_data, list):
            self.report({'ERROR'}, "JSON is not a list of labels.")
            return {'CANCELLED'}
            
        existing_labels = set()
        for obj in context.scene.objects:
            if obj.name.startswith("label-") and "dot_label_data" in obj:
                data = obj["dot_label_data"]
                desc = data.get("description", "")
                anim = data.get("animdata", "")
                existing_labels.add((desc, anim))

        bpy.ops.mesh.primitive_cube_add(size=0.01)
        base_cube = bpy.context.object
        base_cube.data.name = "Cube.label.mesh"
        cube_mesh = base_cube.data.copy()
        bpy.data.objects.remove(base_cube)
        
        bpy.ops.mesh.primitive_ico_sphere_add(radius=0.01, subdivisions=1)
        base_sphere = bpy.context.object
        base_sphere.data.name = "Icosphere.dot.mesh"
        sphere_mesh = base_sphere.data.copy()
        bpy.data.objects.remove(base_sphere)
        
        transparent_mat = create_transparent_material("mat-labelmat")
        
        created_count = 0
        skipped_count = 0
        has_position_data = False
        
        for item in json_data:
            try:
                description = item['text'][0]['text']
                first_frame = item['animation']['frame']['first_value']
                second_frame = item['animation']['frame']['second_value']
                animdata = f"{first_frame}-{second_frame}"
                
                if (description, animdata) in existing_labels:
                    skipped_count += 1
                    continue
                
                # READ POSITION FROM JSON (with coordinate conversion back to Blender)
                rot = (0, 0, 0)  # Default rotation
                
                if 'position' in item:
                    has_position_data = True
                    # Convert from model-viewer coordinates back to Blender
                    # Export was: x=x, y=z, z=-y (Blender -> model-viewer)
                    # So import is: x=x, y=-z, z=y (model-viewer -> Blender)
                    viewer_pos = item['position']
                    loc = (
                        viewer_pos.get('x', 0.0),
                        -viewer_pos.get('z', 0.0),  # model-viewer Z becomes -Y in Blender
                        viewer_pos.get('y', 0.0)    # model-viewer Y becomes Z in Blender
                    )
                    print(f"📍 Importing '{description}' at position: {loc}")
                else:
                    # Fallback to cursor location if no position in JSON
                    loc = context.scene.cursor.location.copy()
                    print(f"⚠️ No position data for '{description}', using cursor: {loc}")
                
                num = get_next_label_number()
                label_name = f"label-{str(num).zfill(3)}"
                dot_name = f"dot-{str(num).zfill(3)}"
                
                label_obj = bpy.data.objects.new(label_name, cube_mesh.copy())
                label_obj.location = loc
                label_obj.rotation_euler = rot
                label_obj.scale = (0.01, 0.01, 0.01)
                context.collection.objects.link(label_obj)
                label_obj.data.materials.append(transparent_mat)
                label_obj.display_type = 'WIRE'
                label_obj.show_all_edges = True
                label_obj.show_wire = True
                label_obj.show_name = True
                
                label_obj["dot_label_data"] = {
                    "description": description,
                    "animdata": animdata
                }
                
                dot_obj = bpy.data.objects.new(dot_name, sphere_mesh.copy())
                dot_obj.location = loc
                dot_obj.rotation_euler = rot
                dot_obj.scale = (0.01, 0.01, 0.01)
                context.collection.objects.link(dot_obj)
                dot_obj.data.materials.append(transparent_mat)
                dot_obj.show_name = True
                
                dot_obj["dot_label_data"] = {
                    "description": description,
                    "animdata": animdata
                }
                
                created_count += 1
            except (KeyError, IndexError) as e:
                self.report({'WARNING'}, f"Skipping malformed entry")
                continue

        # Report with position data info
        if has_position_data:
            self.report({'INFO'}, f"✅ Created: {created_count} (with positions). Skipped: {skipped_count}.")
        else:
            self.report({'WARNING'}, f"⚠️ Created: {created_count} at cursor (NO position data in JSON!). Skipped: {skipped_count}. Re-export labels to include positions!")
        
        return {'FINISHED'}

class UNIFIED_OT_fetch_from_ipr(bpy.types.Operator):
    """Fetch fresh JSON labels from running IPR server"""
    bl_idname = "unified.fetch_from_ipr"
    bl_label = "Fetch Labels from IPR"
    bl_description = "Fetch updated label data from the IPR temp directory"
    
    def execute(self, context):
        # Check if IPR is running
        if not ipr_server_state['server']:
            self.report({'ERROR'}, "IPR server is not running! Start IPR first.")
            return {'CANCELLED'}
        
        temp_dir = ipr_server_state.get('temp_dir')
        if not temp_dir or not os.path.exists(temp_dir):
            self.report({'ERROR'}, "IPR temp directory not found!")
            return {'CANCELLED'}
        
        # Look for JSON files in IPR temp directory
        print(f"\n🔍 Looking in IPR temp: {temp_dir}")
        json_files = [f for f in os.listdir(temp_dir) if f.endswith('.json')]
        
        if not json_files:
            self.report({'WARNING'}, "No JSON files found! Export labels from web viewer first!")
            return {'CANCELLED'}
        
        # Use the most recent JSON file
        json_files.sort(key=lambda x: os.path.getmtime(os.path.join(temp_dir, x)), reverse=True)
        json_path = os.path.join(temp_dir, json_files[0])
        
        # Get file modification time
        import datetime
        mod_time = os.path.getmtime(json_path)
        mod_datetime = datetime.datetime.fromtimestamp(mod_time)
        time_str = mod_datetime.strftime("%Y-%m-%d %H:%M:%S")
        
        print(f"\n🔄 ========== FETCHING FROM IPR ==========")
        print(f"📂 Temp Directory: {temp_dir}")
        print(f"📄 Reading JSON: {json_files[0]}")
        print(f"🕐 Last Modified: {time_str}")
        print(f"📍 Full Path: {json_path}")
        print(f"=" * 45 + "\n")
        
        # Read JSON
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to read JSON: {e}")
            return {'CANCELLED'}
        
        if not isinstance(json_data, list):
            self.report({'ERROR'}, "JSON is not a list of labels.")
            return {'CANCELLED'}
        
        # Get existing labels (map by label number for updating)
        existing_labels_map = {}
        for obj in context.scene.objects:
            if obj.name.startswith("label-") and "dot_label_data" in obj:
                # Extract label number from name (e.g., "label-001" -> 1)
                label_num_str = obj.name.replace("label-", "")
                try:
                    label_num = int(label_num_str)
                    existing_labels_map[label_num] = obj
                except ValueError:
                    pass
        
        # Create base meshes
        bpy.ops.mesh.primitive_cube_add(size=0.01)
        base_cube = bpy.context.object
        base_cube.data.name = "Cube.label.mesh"
        cube_mesh = base_cube.data.copy()
        bpy.data.objects.remove(base_cube)
        
        bpy.ops.mesh.primitive_ico_sphere_add(radius=0.01, subdivisions=1)
        base_sphere = bpy.context.object
        base_sphere.data.name = "Icosphere.dot.mesh"
        sphere_mesh = base_sphere.data.copy()
        bpy.data.objects.remove(base_sphere)
        
        transparent_mat = create_transparent_material("mat-labelmat")
        
        created_count = 0
        updated_count = 0
        has_position_data = False
        
        # Import/Update labels
        for item in json_data:
            try:
                description = item['text'][0]['text']
                first_frame = item['animation']['frame']['first_value']
                second_frame = item['animation']['frame']['second_value']
                animdata = f"{first_frame}-{second_frame}"
                label_id = item.get('id', None)
                
                # Check if label already exists by ID
                if label_id and label_id in existing_labels_map:
                    # UPDATE existing label
                    label_obj = existing_labels_map[label_id]
                    
                    # Update description and animdata
                    label_obj["dot_label_data"] = {
                        "description": description,
                        "animdata": animdata
                    }
                    
                    # Update corresponding dot object
                    dot_name = label_obj.name.replace("label-", "dot-")
                    dot_obj = context.scene.objects.get(dot_name)
                    if dot_obj:
                        dot_obj["dot_label_data"] = {
                            "description": description,
                            "animdata": animdata
                        }
                    
                    # Update position if available
                    if 'position' in item:
                        has_position_data = True
                        viewer_pos = item['position']
                        new_loc = (
                            viewer_pos.get('x', 0.0),
                            -viewer_pos.get('z', 0.0),
                            viewer_pos.get('y', 0.0)
                        )
                        label_obj.location = new_loc
                        if dot_obj:
                            dot_obj.location = new_loc
                        
                        print(f"✅ Updated label-{str(label_id).zfill(3)}: '{description}' | Frames: {animdata} | Position: {new_loc}")
                    else:
                        print(f"✅ Updated label-{str(label_id).zfill(3)}: '{description}' | Frames: {animdata} (no position)")
                    
                    updated_count += 1
                    continue  # Skip to next label
                
                rot = (0, 0, 0)
                
                if 'position' in item:
                    has_position_data = True
                    viewer_pos = item['position']
                    loc = (
                        viewer_pos.get('x', 0.0),
                        -viewer_pos.get('z', 0.0),
                        viewer_pos.get('y', 0.0)
                    )
                    print(f"📍 Fetching '{description}' at position: {loc}")
                else:
                    loc = context.scene.cursor.location.copy()
                    print(f"⚠️ No position data for '{description}', using cursor: {loc}")
                
                num = get_next_label_number()
                label_name = f"label-{str(num).zfill(3)}"
                dot_name = f"dot-{str(num).zfill(3)}"
                
                label_obj = bpy.data.objects.new(label_name, cube_mesh.copy())
                label_obj.location = loc
                label_obj.rotation_euler = rot
                label_obj.scale = (0.01, 0.01, 0.01)
                context.collection.objects.link(label_obj)
                label_obj.data.materials.append(transparent_mat)
                label_obj.display_type = 'WIRE'
                label_obj.show_all_edges = True
                label_obj.show_wire = True
                label_obj.show_name = True
                
                label_obj["dot_label_data"] = {
                    "description": description,
                    "animdata": animdata
                }
                
                dot_obj = bpy.data.objects.new(dot_name, sphere_mesh.copy())
                dot_obj.location = loc
                dot_obj.rotation_euler = rot
                dot_obj.scale = (0.01, 0.01, 0.01)
                context.collection.objects.link(dot_obj)
                dot_obj.data.materials.append(transparent_mat)
                dot_obj.show_name = True
                
                dot_obj["dot_label_data"] = {
                    "description": description,
                    "animdata": animdata
                }
                
                created_count += 1
            except (KeyError, IndexError) as e:
                self.report({'WARNING'}, f"Skipping malformed entry")
                continue
        
        # Report
        total_processed = created_count + updated_count
        
        if total_processed == 0:
            self.report({'WARNING'}, f"⚠️ No labels to fetch. JSON might be empty or all labels already up-to-date.")
        elif has_position_data:
            parts = []
            if created_count > 0:
                parts.append(f"created {created_count}")
            if updated_count > 0:
                parts.append(f"updated {updated_count}")
            self.report({'INFO'}, f"✅ Fetched from IPR: {', '.join(parts)} labels (with positions)!")
        else:
            self.report({'WARNING'}, f"⚠️ Fetched from IPR: {total_processed} labels but NO position data in JSON!")
        
        print(f"✅ Fetch complete: {created_count} created, {updated_count} updated")
        return {'FINISHED'}

class UNIFIED_OT_open_ipr_folder(bpy.types.Operator):
    """Open IPR temp folder in file explorer"""
    bl_idname = "unified.open_ipr_folder"
    bl_label = "Open IPR Folder"
    bl_description = "Open the IPR temp directory in file explorer to copy JSON files"
    
    def execute(self, context):
        temp_dir = ipr_server_state.get('temp_dir')
        
        if not temp_dir or not os.path.exists(temp_dir):
            self.report({'ERROR'}, "IPR temp directory not found!")
            return {'CANCELLED'}
        
        print(f"\n📂 Opening IPR temp folder: {temp_dir}")
        
        try:
            system = platform.system()
            if system == 'Windows':
                os.startfile(temp_dir)
            elif system == 'Darwin':  # macOS
                subprocess.Popen(['open', temp_dir])
            else:  # Linux
                subprocess.Popen(['xdg-open', temp_dir])
            
            self.report({'INFO'}, f"📂 Opened IPR folder")
            print(f"✅ Folder opened successfully!")
            print(f"💡 Copy your exported JSON here, then click 'Fetch from IPR'")
            
        except Exception as e:
            self.report({'ERROR'}, f"Failed to open folder: {str(e)}")
            print(f"❌ Error: {e}")
            return {'CANCELLED'}
        
        return {'FINISHED'}

class UNIFIED_OT_save_ipr_glb(bpy.types.Operator):
    """Save IPR GLB to project folder"""
    bl_idname = "unified.save_ipr_glb"
    bl_label = "Save IPR GLB"
    bl_description = "Copy the IPR temp GLB to your project folder as a permanent file"
    
    def execute(self, context):
        # Check if blend file is saved
        blend_file_path = bpy.data.filepath
        if not blend_file_path:
            self.report({'ERROR'}, "Please save your blend file first!")
            return {'CANCELLED'}
        
        # Check if IPR is running
        temp_dir = ipr_server_state.get('temp_dir')
        if not temp_dir or not os.path.exists(temp_dir):
            self.report({'ERROR'}, "IPR temp directory not found! Start IPR first.")
            return {'CANCELLED'}
        
        # Find GLB in temp folder
        blend_name = os.path.splitext(os.path.basename(blend_file_path))[0]
        temp_glb_path = os.path.join(temp_dir, f"{blend_name}.glb")
        
        if not os.path.exists(temp_glb_path):
            self.report({'ERROR'}, f"GLB not found in temp folder: {blend_name}.glb")
            return {'CANCELLED'}
        
        # Destination path (same location as blend file)
        dest_glb_path = os.path.splitext(blend_file_path)[0] + ".glb"
        
        print(f"\n💾 ========== SAVING IPR GLB ==========")
        print(f"   From: {temp_glb_path}")
        print(f"   To:   {dest_glb_path}")
        
        try:
            # Copy the file
            shutil.copy2(temp_glb_path, dest_glb_path)
            
            # Get file size
            file_size = os.path.getsize(dest_glb_path)
            size_mb = file_size / (1024 * 1024)
            
            print(f"   Size: {size_mb:.2f} MB")
            print(f"=" * 40 + "\n")
            print(f"✅ GLB saved successfully!")
            
            self.report({'INFO'}, f"✅ Saved GLB: {os.path.basename(dest_glb_path)} ({size_mb:.2f} MB)")
            return {'FINISHED'}
            
        except Exception as e:
            print(f"❌ Error saving GLB: {e}")
            self.report({'ERROR'}, f"Failed to save GLB: {str(e)}")
            return {'CANCELLED'}

class UNIFIED_OT_export_data(bpy.types.Operator):
    bl_idname = "unified.export_data"
    bl_label = "Export Label Data (HTML/JSON)"
    bl_description = "Exports dot label data to HTML and JSON"

    def execute(self, context):
        try:
            for obj in bpy.data.objects:
                if obj.name.startswith("label-") or obj.name.startswith("dot-"):
                    if "dot_label_data" in obj:
                        description = obj["dot_label_data"].get("description", "")
                        if description:
                            description_suggester.add_description(description)
            
            description_suggester.save_data()

            blend_file_path = bpy.data.filepath
            if not blend_file_path:
                self.report({'ERROR'}, "Please save your blend file first")
                return {'CANCELLED'}

            label_groups = {}
            for obj in bpy.data.objects:
                if obj.name.startswith("dot-") or obj.name.startswith("label-"):
                    parts = obj.name.split("-")
                    if len(parts) > 1:
                        num = parts[-1]
                        if num.isdigit():
                            if num not in label_groups:
                                label_groups[num] = {"dot": None, "label": None}
                            if obj.name.startswith("dot-"):
                                label_groups[num]["dot"] = obj
                            else:
                                label_groups[num]["label"] = obj

            json_path = os.path.splitext(blend_file_path)[0] + "_dot_labels.json"
            html_path = os.path.splitext(blend_file_path)[0] + "_dot_labels.html"

            json_data = []
            for num in sorted(label_groups.keys()):
                group = label_groups[num]
                label_obj = group.get("label")
                if label_obj and "dot_label_data" in label_obj:
                    data = label_obj["dot_label_data"]
                    description = data.get("description", "")
                    animdata = data.get("animdata", "")
                    
                    first_value = 32
                    second_value = 160
                    if animdata:
                        parts = animdata.split("-")
                        if len(parts) == 2:
                            try:
                                first_value = int(parts[0])
                                second_value = int(parts[1])
                            except ValueError:
                                pass

                    # Get label object's world position for the viewer
                    position = {"x": 0, "y": 0, "z": 0}
                    if label_obj:
                        world_pos = label_obj.matrix_world.translation
                        position = {
                            "x": round(world_pos.x, 4),
                            "y": round(world_pos.z, 4),  # Blender Z becomes Y in model-viewer
                            "z": round(-world_pos.y, 4)  # Blender Y becomes -Z in model-viewer
                        }
                    
                    label_entry = {
                        "text": [{"text": description, "lang": "en"}],
                        "isAnimation": True,
                        "animation": {
                            "frame": {
                                "first_value": first_value,
                                "second_value": second_value
                            }
                        },
                        "position": position,
                        "label_name": label_obj.name if label_obj else f"label-{num}"
                    }
                    json_data.append(label_entry)

            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, indent=4, ensure_ascii=False)

            # Generate comprehensive HTML report matching AutoLMbyAman format
            self._generate_comprehensive_html(context, blend_file_path, label_groups, html_path)

            self.report({'INFO'}, f"Exported to: {json_path} and {html_path}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Error exporting: {str(e)}")
            return {'CANCELLED'}
    
    def _generate_comprehensive_html(self, context, blend_file_path, label_groups, html_path):
        """Generate comprehensive HTML report with metadata and animation details"""
        # Collect metadata
        total_triangles = 0
        object_names = []
        material_names = []
        animated_objects = []
        total_actions = 0
        animation_details = []
        
        for obj in bpy.data.objects:
            if obj.type == 'MESH':
                total_triangles += sum(len(p.vertices) - 2 for p in obj.data.polygons)
                object_names.append(obj.name)
                for material_slot in obj.material_slots:
                    if material_slot.material:
                        material_names.append(material_slot.material.name)
            
            # Collect animation data
            if obj.animation_data and obj.animation_data.action:
                animated_objects.append(obj)
                total_actions += 1
                
                action = obj.animation_data.action
                fcurves = action.fcurves
                
                anim_types = set()
                keyframes = set()
                for fc in fcurves:
                    anim_types.add(fc.data_path)
                    for key in fc.keyframe_points:
                        keyframes.add(int(key.co.x))
                
                if keyframes:
                    duration = max(keyframes) - min(keyframes)
                    animation_details.append(f"""
                        <div class="animation-info">
                            <h4>{obj.name}</h4>
                            <p class="animation-type">Animation Types: {', '.join(anim_types)}</p>
                            <p class="animation-duration">Duration: {duration} frames</p>
                            <p>Frame Range: {min(keyframes)} - {max(keyframes)}</p>
                            <div class="keyframe-list">
                                <p>Keyframes at: {', '.join(map(str, sorted(keyframes)))}</p>
                            </div>
                        </div>
                    """)
        
        # Generate label groups HTML
        label_groups_html = ""
        for num in sorted(label_groups.keys()):
            group = label_groups[num]
            dot_obj = group.get("dot")
            label_obj = group.get("label")

            label_groups_html += f"""
            <div class="label-group">
                <div class="label-number">Label Group {num}</div>
                <div class="label-details">"""

            if label_obj:
                label_mesh_data_name = label_obj.data.name if label_obj.data else "No Mesh Data"
                description = "No description"
                animdata = "No animation data"
                if "dot_label_data" in label_obj:
                    description = label_obj["dot_label_data"].get("description", "No description")
                    animdata = label_obj["dot_label_data"].get("animdata", "No animation data")
                
                label_groups_html += f"""
                    <div class="label-item">
                        <div class="label-name">Label: {label_obj.name}</div>
                        <div class="mesh-name">Mesh: {label_mesh_data_name}</div>
                        <div class="description">Description: {description}</div>
                        <div class="anim-data">Animation Data: {animdata}</div>
                    </div>"""

            if dot_obj:
                animation_info = "No animation"
                if dot_obj.animation_data and dot_obj.animation_data.action:
                    action = dot_obj.animation_data.action
                    fcurves = [fc for fc in action.fcurves if fc.data_path == "scale"]
                    keyframes = set()
                    for fc in fcurves:
                        for key in fc.keyframe_points:
                            keyframes.add(int(key.co.x))
                    if keyframes:
                        animation_info = f"Keyframes at frames: {sorted(keyframes)}"
                
                label_groups_html += f"""
                    <div class="label-item">
                        <div class="label-name">Dot: {dot_obj.name}</div>
                        <div class="anim-data">Animation: {animation_info}</div>
                    </div>"""

            label_groups_html += """
                </div>
            </div>"""
        
        # Get GLB file size if it exists
        glb_path = os.path.splitext(blend_file_path)[0] + ".glb"
        glb_size_mb = 0
        if os.path.exists(glb_path):
            glb_size_mb = os.path.getsize(glb_path) / (1024 * 1024)
        
        # Format lists
        object_list = "\n".join([f"<li>{name}</li>" for name in sorted(object_names)])
        material_list = "\n".join([f"<li>{name}</li>" for name in sorted(set(material_names))])
        
        # Determine status
        triangle_status = "OK" if total_triangles < 100000 else "HIGH"
        triangle_status_class = "status-ok" if total_triangles < 100000 else "status-warning"
        
        naming_status = "OK" if all(name.startswith(("dot-", "label-", "mesh-")) for name in object_names) else "Needs Review"
        naming_status_class = "status-ok" if naming_status == "OK" else "status-warning"
        
        material_naming_status = "OK" if all(name.startswith("mat-") for name in material_names) else "Needs Review"
        material_naming_status_class = "status-ok" if material_naming_status == "OK" else "status-warning"
        
        glb_size_status = "OK" if glb_size_mb <= 20 else "LARGE"
        glb_size_status_class = "status-ok" if glb_size_mb <= 20 else "status-warning"
        
        # Get scene frame range
        scene = context.scene
        scene_frame_start = scene.frame_start
        scene_frame_end = scene.frame_end
        
        # Generate timestamp
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        
        # Create full HTML with all styling and tabs (matching the reference)
        html_content = self._get_html_template().format(
            script_name=bl_info["name"],
            script_version=".".join(str(v) for v in bl_info["version"]),
            script_author=bl_info["author"],
            timestamp=timestamp,
            label_groups=label_groups_html,
            object_list=object_list,
            material_list=material_list,
            total_triangles=total_triangles,
            object_count=len(object_names),
            material_count=len(set(material_names)),
            triangle_status=triangle_status,
            triangle_status_class=triangle_status_class,
            naming_status=naming_status,
            naming_status_class=naming_status_class,
            material_naming_status=material_naming_status,
            material_naming_status_class=material_naming_status_class,
            glb_size=round(glb_size_mb, 2),
            glb_size_status=glb_size_status,
            glb_size_status_class=glb_size_status_class,
            animated_objects_count=len(animated_objects),
            total_actions=total_actions,
            scene_frame_start=scene_frame_start,
            scene_frame_end=scene_frame_end,
            animation_details="\n".join(animation_details) if animation_details else "<p>No animated objects found</p>"
        )
        
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
    
    def _get_html_template(self):
        """Returns the comprehensive HTML template matching AutoLMbyAman format"""
        return """<!DOCTYPE html>
<html>
<head>
    <title>Dot Label Data Export</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background-color: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .script-header {{
            background-color: #2c3e50;
            color: white;
            padding: 15px;
            margin: -20px -20px 20px -20px;
            border-radius: 8px 8px 0 0;
            position: relative;
        }}
        .script-header h1 {{
            margin: 0;
            padding: 0;
            border: none;
            font-size: 18px;
            font-weight: normal;
            display: inline-block;
            color: white;
        }}
        .script-header p {{
            margin: 5px 0 0 0;
            opacity: 0.8;
            font-size: 14px;
        }}
        .script-header .version {{
            color: #27ae60;
            font-weight: bold;
        }}
        .script-header .timestamp {{
            font-style: italic;
            font-size: 12px;
            margin-top: 5px;
        }}
        .script-header .developer {{
            position: absolute;
            right: 15px;
            top: 15px;
            font-size: 14px;
            font-style: italic;
            color: white;
        }}
        h1, h2, h3 {{
            color: #333;
            border-bottom: 2px solid #eee;
            padding-bottom: 10px;
        }}
        .section {{
            margin: 20px 0;
            padding: 20px;
            border: 1px solid #ddd;
            border-radius: 4px;
            background-color: #fff;
        }}
        .label-group {{
            margin: 15px 0;
            padding: 15px;
            border: 1px solid #ddd;
            border-radius: 4px;
            background-color: #fff;
        }}
        .label-number {{
            font-size: 1.2em;
            color: #2c3e50;
            margin-bottom: 10px;
        }}
        .label-details {{
            margin-left: 20px;
        }}
        .label-item {{
            margin: 10px 0;
            padding: 10px;
            background-color: #f8f9fa;
            border-radius: 4px;
        }}
        .label-name {{
            font-weight: bold;
            color: #2c3e50;
        }}
        .mesh-name {{
            color: #666;
            font-style: italic;
        }}
        .description {{
            color: #34495e;
            margin-top: 5px;
        }}
        .anim-data {{
            color: #27ae60;
            margin-top: 5px;
        }}
        .metadata-table {{
            width: 100%;
            border-collapse: collapse;
            margin: 15px 0;
        }}
        .metadata-table th, .metadata-table td {{
            padding: 8px;
            border: 1px solid #ddd;
            text-align: left;
        }}
        .metadata-table th {{
            background-color: #f8f9fa;
            font-weight: bold;
        }}
        .report-item {{
            margin: 10px 0;
            padding: 10px;
            border-radius: 4px;
        }}
        .status-ok {{
            color: #27ae60;
        }}
        .status-warning {{
            color: #f39c12;
        }}
        .tab {{
            overflow: hidden;
            border: 1px solid #ccc;
            background-color: #f1f1f1;
            border-radius: 4px 4px 0 0;
        }}
        .tab button {{
            background-color: inherit;
            float: left;
            border: none;
            outline: none;
            cursor: pointer;
            padding: 14px 16px;
            transition: 0.3s;
            font-size: 16px;
        }}
        .tab button:hover {{
            background-color: #ddd;
        }}
        .tab button.active {{
            background-color: #ccc;
        }}
        .tabcontent {{
            display: none;
            padding: 6px 12px;
            border: 1px solid #ccc;
            border-top: none;
            border-radius: 0 0 4px 4px;
        }}
        .animation-info {{
            margin: 10px 0;
            padding: 10px;
            background-color: #f8f9fa;
            border-radius: 4px;
        }}
        .animation-details {{
            margin-left: 20px;
            padding: 5px;
            border-left: 3px solid #27ae60;
        }}
        .keyframe-list {{
            margin-left: 20px;
            color: #666;
        }}
        .animation-type {{
            font-weight: bold;
            color: #2c3e50;
        }}
        .animation-duration {{
            color: #27ae60;
            font-weight: bold;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="script-header">
            <h1>{script_name}</h1>
            <span class="developer">Concept Designer: {script_author}</span>
            <p>Version: <span class="version">{script_version}</span></p>
            <p class="timestamp">Generated on: {timestamp}</p>
        </div>
        
        <div class="tab">
            <button class="tablinks active" onclick="openTab(event, 'Labels')">Labels Information</button>
            <button class="tablinks" onclick="openTab(event, 'Metadata')">GLB Metadata</button>
            <button class="tablinks" onclick="openTab(event, 'Animation')">Animation Details</button>
            <button class="tablinks" onclick="openTab(event, 'Reports')">Reports</button>
        </div>

        <div id="Labels" class="tabcontent" style="display: block;">
            <div class="label-groups">
                {label_groups}
            </div>
        </div>

        <div id="Metadata" class="tabcontent">
            <div class="section">
                <h2>GLB Metadata</h2>
                <table class="metadata-table">
                    <tr>
                        <th>Property</th>
                        <th>Value</th>
                    </tr>
                    <tr>
                        <td>Total Triangles</td>
                        <td class="status-ok">{total_triangles}</td>
                    </tr>
                    <tr>
                        <td>Objects</td>
                        <td>{object_count}</td>
                    </tr>
                    <tr>
                        <td>Materials</td>
                        <td>{material_count}</td>
                    </tr>
                    <tr>
                        <td>GLB File Size</td>
                        <td class="{glb_size_status_class}">{glb_size} MB ({glb_size_status})</td>
                    </tr>
                </table>
                
                <h3>Object Names</h3>
                <ul>
                    {object_list}
                </ul>
                
                <h3>Material Names</h3>
                <ul>
                    {material_list}
                </ul>
            </div>
        </div>

        <div id="Animation" class="tabcontent">
            <div class="section">
                <h2>Animation Details</h2>
                <div class="animation-info">
                    <h3>Scene Animation Summary</h3>
                    <p>Total Animated Objects: {animated_objects_count}</p>
                    <p>Total Animation Actions: {total_actions}</p>
                    <p>Scene Frame Range: {scene_frame_start} - {scene_frame_end}</p>
                </div>
                
                <div class="animation-details">
                    {animation_details}
                </div>
            </div>
        </div>

        <div id="Reports" class="tabcontent">
            <div class="section">
                <h2>Reports</h2>
                <div class="report-item">
                    <h3>Triangle Count</h3>
                    <p class="{triangle_status_class}">Total Triangles: {total_triangles} ({triangle_status})</p>
                </div>
                <div class="report-item">
                    <h3>File Size</h3>
                    <p class="{glb_size_status_class}">GLB File Size: {glb_size} MB ({glb_size_status})</p>
                </div>
                <div class="report-item">
                    <h3>Naming Conventions</h3>
                    <p class="{naming_status_class}">Object Naming: {naming_status}</p>
                    <p class="{material_naming_status_class}">Material Naming: {material_naming_status}</p>
                </div>
            </div>
        </div>
    </div>

    <script>
    function openTab(evt, tabName) {{
        var i, tabcontent, tablinks;
        tabcontent = document.getElementsByClassName("tabcontent");
        for (i = 0; i < tabcontent.length; i++) {{
            tabcontent[i].style.display = "none";
        }}
        tablinks = document.getElementsByClassName("tablinks");
        for (i = 0; i < tablinks.length; i++) {{
            tablinks[i].className = tablinks[i].className.replace(" active", "");
        }}
        document.getElementById(tabName).style.display = "block";
        evt.currentTarget.className += " active";
    }}
    </script>
</body>
</html>"""

class UNIFIED_OT_export_labels_only(bpy.types.Operator):
    bl_idname = "unified.export_labels_only"
    bl_label = "Export Labels Only"
    bl_description = "Export only label data to a simple JSON file"

    def execute(self, context):
        try:
            blend_file_path = bpy.data.filepath
            if not blend_file_path:
                self.report({'ERROR'}, "Please save your blend file first")
                return {'CANCELLED'}

            # Collect all labels
            labels_data = []
            for obj in sorted(bpy.data.objects, key=lambda x: x.name):
                if obj.name.startswith("label-") and "dot_label_data" in obj:
                    data = obj["dot_label_data"]
                    label_entry = {
                        "name": obj.name,
                        "description": data.get("description", ""),
                        "animdata": data.get("animdata", ""),
                        "location": [obj.location.x, obj.location.y, obj.location.z]
                    }
                    labels_data.append(label_entry)

            if not labels_data:
                self.report({'WARNING'}, "No labels found to export")
                return {'CANCELLED'}

            # Save to JSON
            json_path = os.path.splitext(blend_file_path)[0] + "_labels_only.json"
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(labels_data, f, indent=4, ensure_ascii=False)

            self.report({'INFO'}, f"Exported {len(labels_data)} labels to: {json_path}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Error exporting labels: {str(e)}")
            return {'CANCELLED'}

class UNIFIED_OT_edit_properties(bpy.types.Operator):
    bl_idname = "unified.edit_properties"
    bl_label = "Edit Properties"
    bl_description = "Edit properties of the selected dot/label object"

    description: bpy.props.StringProperty(name="Description", default="")
    animdata: bpy.props.StringProperty(name="Animation Data", default="")
    mesh_name: bpy.props.StringProperty(name="Mesh Name", default="")

    def invoke(self, context, event):
        obj = context.active_object
        if obj:
            if "dot_label_data" in obj:
                self.description = obj["dot_label_data"].get("description", "")
                self.animdata = obj["dot_label_data"].get("animdata", "")
            if obj.data:
                self.mesh_name = obj.data.name
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        obj = context.active_object
        if not obj:
            self.report({'ERROR'}, "No active object selected")
            return {'CANCELLED'}

        if not obj.name.startswith("dot-") and not obj.name.startswith("label-"):
            self.report({'ERROR'}, "Selected object is not a dot or label")
            return {'CANCELLED'}

        obj["dot_label_data"] = {
            "description": self.description,
            "animdata": self.animdata
        }

        if self.mesh_name and obj.data:
            obj.data.name = self.mesh_name

        return {'FINISHED'}

class UNIFIED_OT_shift_animation(bpy.types.Operator):
    bl_idname = "unified.shift_animation"
    bl_label = "Shift Animation Data"
    bl_description = "Shift all dot label animation data by specified frames"

    frame_offset: bpy.props.IntProperty(
        name="Frame Offset",
        default=0,
        description="Number of frames to shift (positive = forward, negative = backward)"
    )

    def execute(self, context):
        try:
            objects = [obj for obj in bpy.data.objects if obj.name.startswith("dot-") or obj.name.startswith("label-")]
            
            for obj in objects:
                if "dot_label_data" in obj:
                    current_data = obj["dot_label_data"]
                    
                    new_data = {
                        "description": current_data.get("description", ""),
                        "animdata": current_data.get("animdata", "")
                    }
                    
                    if new_data["animdata"]:
                        parts = new_data["animdata"].split("-")
                        if len(parts) == 2:
                            try:
                                start_frame = int(parts[0])
                                end_frame = int(parts[1])
                                
                                new_start_frame = start_frame + self.frame_offset
                                new_end_frame = end_frame + self.frame_offset
                                
                                new_data["animdata"] = f"{new_start_frame}-{new_end_frame}"
                            except ValueError:
                                pass
                    
                    obj["dot_label_data"] = new_data
                    obj.update_tag()
            
            for area in context.screen.areas:
                if area.type == 'VIEW_3D' or area.type == 'PROPERTIES':
                    area.tag_redraw()
            
            self.report({'INFO'}, f"Shifted animation data by {self.frame_offset} frames")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Error shifting animation data: {str(e)}")
            return {'CANCELLED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "frame_offset")

class UNIFIED_OT_add_timeline_markers(bpy.types.Operator):
    bl_idname = "unified.add_timeline_markers"
    bl_label = "Add Timeline Markers"
    bl_description = "Adds timeline markers based on label animation data"

    def execute(self, context):
        try:
            scene = context.scene
            markers_to_remove = []
            for marker in scene.timeline_markers:
                if marker.name.endswith("_start") or marker.name.endswith("_end"):
                    markers_to_remove.append(marker)
            for marker in markers_to_remove:
                scene.timeline_markers.remove(marker)

            for obj in context.selected_objects:
                if obj.name.startswith("label-"):
                    if "dot_label_data" in obj:
                        animdata = obj["dot_label_data"].get("animdata", "")
                        if animdata:
                            parts = animdata.split("-")
                            if len(parts) == 2:
                                try:
                                    start_frame = int(parts[0])
                                    end_frame = int(parts[1])
                                    
                                    description = obj["dot_label_data"].get("description", "")
                                    marker_base_name = obj.name
                                    if description:
                                        clean_description = description.replace(" ", "_")
                                        marker_base_name = f"{obj.name}_{clean_description}"

                                    start_marker = scene.timeline_markers.new(f"{marker_base_name}_start", frame=start_frame)
                                    start_marker["dot_label_name"] = obj.name
                                    
                                    end_marker = scene.timeline_markers.new(f"{marker_base_name}_end", frame=end_frame)
                                    end_marker["dot_label_name"] = obj.name

                                except ValueError:
                                    self.report({'WARNING'}, f"Could not parse animdata for {obj.name}")

            self.report({'INFO'}, "Timeline markers added successfully!")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Error adding timeline markers: {str(e)}")
            return {'CANCELLED'}

class UNIFIED_OT_sync_markers_to_data(bpy.types.Operator):
    bl_idname = "unified.sync_markers_to_data"
    bl_label = "Sync Markers to Data"
    bl_description = "Reads timeline marker positions and updates label animation data"

    def execute(self, context):
        try:
            scene = context.scene
            updated_labels = {}

            # Collect markers
            markers = {}
            for marker in scene.timeline_markers:
                if "dot_label_name" in marker and (marker.name.endswith("_start") or marker.name.endswith("_end")):
                    label_name = marker["dot_label_name"]
                    if label_name not in markers:
                        markers[label_name] = {"start": None, "end": None}
                    
                    if marker.name.endswith("_start"):
                        markers[label_name]["start"] = marker
                    elif marker.name.endswith("_end"):
                        markers[label_name]["end"] = marker

            if not markers:
                self.report({'WARNING'}, "No markers found. Use 'Add Markers' first to create markers from labels")
                return {'CANCELLED'}

            # Update labels and dots
            for label_name, marker_pair in markers.items():
                label_obj = bpy.data.objects.get(label_name)
                if label_obj and "dot_label_data" in label_obj:
                    if marker_pair["start"] and marker_pair["end"]:
                        new_start_frame = int(marker_pair["start"].frame)
                        new_end_frame = int(marker_pair["end"].frame)
                        
                        current_data = dict(label_obj["dot_label_data"])
                        old_animdata_string = current_data.get("animdata")
                        new_animdata_string = f"{new_start_frame}-{new_end_frame}"
                        
                        if old_animdata_string != new_animdata_string:
                            # Update label object
                            current_data["animdata"] = new_animdata_string
                            label_obj["dot_label_data"] = current_data
                            label_obj.update_tag()
                            
                            # Also update corresponding dot object
                            dot_name = label_name.replace("label-", "dot-")
                            dot_obj = bpy.data.objects.get(dot_name)
                            if dot_obj and "dot_label_data" in dot_obj:
                                dot_data = dict(dot_obj["dot_label_data"])
                                dot_data["animdata"] = new_animdata_string
                                dot_obj["dot_label_data"] = dot_data
                                dot_obj.update_tag()
                            
                            updated_labels[label_name] = True
            
            # Force viewport refresh
            for area in context.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()

            if updated_labels:
                self.report({'INFO'}, f"Synced animation data for {len(updated_labels)} labels")
            else:
                self.report({'INFO'}, "No changes needed - markers already match label data")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Error syncing markers: {str(e)}")
            return {'CANCELLED'}

class UNIFIED_OT_remove_all_markers(bpy.types.Operator):
    bl_idname = "unified.remove_all_markers"
    bl_label = "Remove All Timeline Markers"
    bl_description = "Clears all markers from the timeline"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.scene.timeline_markers
    
    def execute(self, context):
        context.scene.timeline_markers.clear()
        self.report({'INFO'}, "All timeline markers removed")
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

class UNIFIED_OT_diagnose_animation(bpy.types.Operator):
    """Diagnose and fix animation range issues before export"""
    bl_idname = "unified.diagnose_animation"
    bl_label = "🔍 Diagnose Animation"
    bl_description = "Check animation range and fix common export issues"
    
    def execute(self, context):
        scene = context.scene
        
        print("\n" + "=" * 60)
        print("🔍 ANIMATION RANGE DIAGNOSTIC")
        print("=" * 60)
        
        # 1. Check Scene Animation Range
        scene_start = scene.frame_start
        scene_end = scene.frame_end
        scene_current = scene.frame_current
        
        print(f"\n📊 SCENE ANIMATION RANGE:")
        print(f"   Start Frame: {scene_start}")
        print(f"   End Frame: {scene_end}")
        print(f"   Current Frame: {scene_current}")
        print(f"   Duration: {scene_end - scene_start + 1} frames")
        
        # 2. Check Action Ranges
        print(f"\n🎬 ACTIONS (Animation Data):")
        actions_found = False
        action_ranges = []
        
        for action in bpy.data.actions:
            if action.fcurves:
                # Get frame range from action
                frame_start = min([min([kp.co[0] for kp in fcurve.keyframe_points]) for fcurve in action.fcurves if fcurve.keyframe_points])
                frame_end = max([max([kp.co[0] for kp in fcurve.keyframe_points]) for fcurve in action.fcurves if fcurve.keyframe_points])
                
                action_ranges.append((action.name, frame_start, frame_end))
                print(f"   • {action.name}: {int(frame_start)}-{int(frame_end)} ({int(frame_end - frame_start + 1)} frames)")
                actions_found = True
        
        if not actions_found:
            print("   ⚠️  No actions with keyframes found")
        
        # 3. Check Object Animation
        print(f"\n📦 ANIMATED OBJECTS:")
        animated_objects = []
        for obj in bpy.data.objects:
            if obj.animation_data and obj.animation_data.action:
                action = obj.animation_data.action
                if action.fcurves:
                    animated_objects.append((obj.name, action.name))
                    print(f"   • {obj.name} → {action.name}")
        
        if not animated_objects:
            print("   ℹ️  No objects with animation actions")
        
        # 4. Detect Issues
        print(f"\n⚠️  POTENTIAL ISSUES:")
        issues = []
        
        # Issue 1: Scene range doesn't match actions
        if action_ranges:
            min_action_start = min([r[1] for r in action_ranges])
            max_action_end = max([r[2] for r in action_ranges])
            
            if scene_start != int(min_action_start) or scene_end != int(max_action_end):
                issues.append(f"Scene range ({scene_start}-{scene_end}) doesn't match action range ({int(min_action_start)}-{int(max_action_end)})")
                print(f"   ❌ Scene range ({scene_start}-{scene_end}) ≠ Action range ({int(min_action_start)}-{int(max_action_end)})")
        
        # Issue 2: Frame start not at 0 or 1
        if scene_start not in [0, 1]:
            issues.append(f"Scene starts at frame {scene_start} (should be 0 or 1)")
            print(f"   ⚠️  Scene starts at frame {scene_start} (GLB prefers starting at 0)")
        
        # Issue 3: Large frame numbers
        if scene_end > 1000:
            issues.append(f"Very long animation ({scene_end} frames)")
            print(f"   ⚠️  Very long animation ({scene_end} frames) - may cause issues")
        
        if not issues:
            print("   ✅ No issues detected!")
        
        # 5. Show what WILL be exported
        print(f"\n📤 WHAT WILL BE EXPORTED (with current settings):")
        print(f"   Scene Frame Range: {scene_start} to {scene_end}")
        print(f"   Total Frames: {scene_end - scene_start + 1}")
        print(f"   Duration at 24fps: {(scene_end - scene_start + 1) / 24:.2f} seconds")
        print(f"   ✅ export_frame_range is set to TRUE (respects scene timeline)")
        
        if action_ranges:
            min_action_start = int(min([r[1] for r in action_ranges]))
            max_action_end = int(max([r[2] for r in action_ranges]))
            print(f"\n   💡 If export_frame_range was FALSE, it would export:")
            print(f"      All keyframes: {min_action_start}-{max_action_end} (ignoring scene timeline)")
        
        # 6. Recommendations
        print(f"\n💡 RECOMMENDATIONS:")
        if action_ranges:
            min_action_start = int(min([r[1] for r in action_ranges]))
            max_action_end = int(max([r[2] for r in action_ranges]))
            
            if scene_start != min_action_start or scene_end != max_action_end:
                print(f"   🔧 Fix: Set scene range to {min_action_start}-{max_action_end}")
                print(f"   💡 Click 'Fix Animation Range' button to auto-fix")
            else:
                print(f"   ✅ Scene range matches action range - ready to export!")
        
        print("=" * 60 + "\n")
        
        # Show report in UI
        if issues:
            self.report({'WARNING'}, f"Found {len(issues)} issue(s) - Check console (Window → Toggle System Console)")
        else:
            self.report({'INFO'}, f"✅ Animation range looks good! Scene: {scene_start}-{scene_end}")
        
        return {'FINISHED'}

class UNIFIED_OT_fix_animation_range(bpy.types.Operator):
    """Automatically fix animation range to match actions"""
    bl_idname = "unified.fix_animation_range"
    bl_label = "🔧 Fix Animation Range"
    bl_description = "Auto-fix scene animation range to match action keyframes"
    
    def execute(self, context):
        scene = context.scene
        
        # Find all actions with keyframes
        action_ranges = []
        for action in bpy.data.actions:
            if action.fcurves:
                try:
                    frame_start = min([min([kp.co[0] for kp in fcurve.keyframe_points]) for fcurve in action.fcurves if fcurve.keyframe_points])
                    frame_end = max([max([kp.co[0] for kp in fcurve.keyframe_points]) for fcurve in action.fcurves if fcurve.keyframe_points])
                    action_ranges.append((frame_start, frame_end))
                except:
                    pass
        
        if not action_ranges:
            self.report({'WARNING'}, "No actions with keyframes found")
            return {'CANCELLED'}
        
        # Get min/max across all actions
        min_frame = int(min([r[0] for r in action_ranges]))
        max_frame = int(max([r[1] for r in action_ranges]))
        
        # Store old values
        old_start = scene.frame_start
        old_end = scene.frame_end
        
        # Set new range
        scene.frame_start = min_frame
        scene.frame_end = max_frame
        
        print(f"\n🔧 ANIMATION RANGE FIXED:")
        print(f"   Old: {old_start}-{old_end}")
        print(f"   New: {min_frame}-{max_frame}")
        print(f"   ✅ Range updated to match action keyframes!\n")
        
        self.report({'INFO'}, f"✅ Fixed! Scene range: {min_frame}-{max_frame} (was {old_start}-{old_end})")
        
        return {'FINISHED'}

class UNIFIED_OT_export_glb(bpy.types.Operator):
    bl_idname = "unified.export_glb"
    bl_label = "Export GLB"
    bl_description = "Exports scene to GLB with Aman's preset settings"

    def execute(self, context):
        try:
            blend_file_path = bpy.data.filepath
            if not blend_file_path:
                self.report({'ERROR'}, "Please save your blend file first")
                return {'CANCELLED'}

            glb_path = os.path.splitext(blend_file_path)[0] + ".glb"
            
            # Get export settings from scene properties
            use_frame_range = context.scene.export_frame_range_enabled
            combine_nla = context.scene.export_nla_combined
            
            # Determine animation mode based on NLA setting
            animation_mode = 'NLA_TRACKS' if combine_nla else 'ACTIONS'
            
            print(f"\n📤 ========== EXPORTING GLB ==========")
            print(f"   Frame Range: {'Scene Timeline' if use_frame_range else 'All Keyframes'}")
            if use_frame_range:
                print(f"   Scene Range: {context.scene.frame_start}-{context.scene.frame_end}")
            print(f"   NLA Tracks: {'Combined' if combine_nla else 'Separate'}")
            print(f"   Animation Mode: {animation_mode}")
            print(f"=" * 40 + "\n")
            
            # Using Aman's preset settings from AutoLMbyAman.py
            # Export with custom properties (extras) and animation settings
            bpy.ops.export_scene.gltf('EXEC_DEFAULT',
                filepath=glb_path,
                export_import_convert_lighting_mode='SPEC',
                gltf_export_id='',
                export_use_gltfpack=False,
                export_gltfpack_tc=True,
                export_gltfpack_tq=8,
                export_gltfpack_si=1.0,
                export_gltfpack_sa=False,
                export_gltfpack_slb=False,
                export_gltfpack_vp=14,
                export_gltfpack_vt=12,
                export_gltfpack_vn=8,
                export_gltfpack_vc=8,
                export_gltfpack_vpi='Integer',
                export_gltfpack_noq=True,
                # export_gltfpack_kn=False,  # ❌ Removed - not available in all Blender versions
                export_format='GLB',
                ui_tab='GENERAL',
                export_copyright='',
                export_image_format='AUTO',
                export_image_add_webp=False,
                export_image_webp_fallback=False,
                export_texture_dir='',
                export_jpeg_quality=75,
                export_image_quality=75,
                export_keep_originals=False,
                export_texcoords=True,
                export_normals=True,
                export_gn_mesh=False,
                export_draco_mesh_compression_enable=False,
                export_draco_mesh_compression_level=6,
                export_draco_position_quantization=14,
                export_draco_normal_quantization=10,
                export_draco_texcoord_quantization=12,
                export_draco_color_quantization=10,
                export_draco_generic_quantization=12,
                export_tangents=False,
                export_materials='EXPORT',
                export_unused_images=False,
                export_unused_textures=False,
                export_vertex_color='MATERIAL',
                export_all_vertex_colors=True,
                export_active_vertex_color_when_no_material=True,
                export_attributes=False,
                use_mesh_edges=False,
                use_mesh_vertices=False,
                export_cameras=False,
                use_selection=False,
                use_visible=False,
                use_renderable=False,
                use_active_collection_with_nested=True,
                use_active_collection=False,
                use_active_scene=False,
                collection='',
                at_collection_center=False,
                export_extras=True,
                export_yup=True,
                export_apply=False,
                export_shared_accessors=False,
                export_animations=True,
                export_frame_range=True,  # ✅ Use scene timeline range!
                export_frame_step=1,
                export_force_sampling=True,
                export_sampling_interpolation_fallback='LINEAR',
                export_pointer_animation=False,
                export_animation_mode='ACTIONS',
                export_nla_strips_merged_animation_name='Animation',
                export_def_bones=False,
                export_hierarchy_flatten_bones=False,
                export_hierarchy_flatten_objs=False,
                export_armature_object_remove=False,
                export_leaf_bone=False,
                export_optimize_animation_size=True,
                export_optimize_animation_keep_anim_armature=True,
                export_optimize_animation_keep_anim_object=False,
                export_optimize_disable_viewport=False,
                export_negative_frame='SLIDE',
                export_anim_slide_to_zero=False,
                export_bake_animation=False,
                export_merge_animation='ACTION',
                export_anim_single_armature=True,
                export_reset_pose_bones=True,
                export_current_frame=False,
                export_rest_position_armature=True,
                export_anim_scene_split_object=True,
                export_skins=True,
                export_influence_nb=4,
                export_all_influences=False,
                export_morph=True,
                export_morph_normal=True,
                export_morph_tangent=False,
                export_morph_animation=True,
                export_morph_reset_sk_data=True,
                export_lights=False,
                export_try_sparse_sk=True,
                export_try_omit_sparse_sk=False,
                export_gpu_instances=False,
                export_action_filter=False,
                export_convert_animation_pointer=False,
                export_nla_strips=True,
                export_original_specular=False,
                export_hierarchy_full_collections=False,
                export_extra_animations=False,
                export_loglevel=-1
            )
            
            self.report({'INFO'}, f"Exported GLB with custom preset: {glb_path}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Error exporting GLB: {str(e)}")
            return {'CANCELLED'}

class UNIFIED_OT_add_word_to_dictionary(bpy.types.Operator):
    bl_idname = "unified.add_word_to_dictionary"
    bl_label = "Add Word to Dictionary"
    bl_description = "Manually add a word to the description suggester dictionary"
    
    new_word: bpy.props.StringProperty(
        name="Word/Phrase",
        default="",
        description="Enter word or phrase to add"
    )

    def execute(self, context):
        if self.new_word:
            description_suggester.add_description(self.new_word)
            description_suggester.save_data()
            self.report({'INFO'}, f"'{self.new_word}' added to dictionary")
        else:
            self.report({'WARNING'}, "Please enter a word or phrase")
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "new_word")

class UNIFIED_OT_toggle_performance_monitor(bpy.types.Operator):
    bl_idname = "unified.toggle_performance_monitor"
    bl_label = "Toggle Performance Monitor"
    bl_description = "Toggle performance monitoring display"
    
    def execute(self, context):
        context.scene.show_performance_stats = not context.scene.show_performance_stats
        performance_monitor.is_monitoring = context.scene.show_performance_stats
        return {'FINISHED'}

class UNIFIED_OT_check_for_updates(bpy.types.Operator):
    bl_idname = "unified.check_for_updates"
    bl_label = "Check for Updates"
    bl_description = "Manually check for new versions"

    def execute(self, context):
        global _last_update_check, _cached_update_info
        _last_update_check = 0
        _cached_update_info = (None, None)
        
        latest_version, download_url = check_for_update()
        
        if latest_version and latest_version > bl_info['version']:
            version_str = '.'.join(str(v) for v in latest_version)
            self.report({'INFO'}, f"New version {version_str} available!")
            if download_url:
                bpy.ops.wm.url_open(url=download_url)
        else:
            self.report({'INFO'}, "You are running the latest version")
            
        for area in context.window.screen.areas:
            if area.type == 'PREFERENCES':
                area.tag_redraw()

        return {'FINISHED'}

class UNIFIED_OT_open_preferences(bpy.types.Operator):
    bl_idname = "unified.open_preferences"
    bl_label = "Open Addon Preferences"
    bl_description = "Open addon preferences to configure paths and settings"
    
    def execute(self, context):
        bpy.ops.preferences.addon_show(module=__name__)
        return {'FINISHED'}

# ============= ASSET LIBRARY OPERATORS =============
class UNIFIED_OT_search_glb_files(bpy.types.Operator):
    bl_idname = "unified.search_glb_files"
    bl_label = "Search GLB Files"
    bl_description = "Search for GLB files in asset library"

    def execute(self, context):
        asset_libraries = bpy.context.preferences.filepaths.asset_libraries
        if len(asset_libraries) == 0:
            self.report({'ERROR'}, "No asset library path defined")
            return {'CANCELLED'}

        asset_folder_path = asset_libraries[0].path
        search_query = context.scene.glb_search_query.lower()

        context.scene.glb_file_results.clear()
        if os.path.isdir(asset_folder_path):
            for root, dirs, files in os.walk(asset_folder_path):
                for file in files:
                    if file.endswith(".glb") and search_query in file.lower():
                        result = context.scene.glb_file_results.add()
                        result.file_path = os.path.join(root, file)

        return {'FINISHED'}

class UNIFIED_OT_import_glb_file(bpy.types.Operator):
    bl_idname = "unified.import_glb_file"
    bl_label = "Import GLB File"
    bl_description = "Import selected GLB file"

    filepath: bpy.props.StringProperty()

    def execute(self, context):
        bpy.ops.import_scene.gltf(filepath=self.filepath)
        return {'FINISHED'}

class UNIFIED_OT_upload_glb_file(bpy.types.Operator):
    bl_idname = "unified.upload_glb_file"
    bl_label = "Upload Selected Object as GLB"
    bl_description = "Export selected object to asset library"

    def execute(self, context):
        asset_libraries = bpy.context.preferences.filepaths.asset_libraries
        if len(asset_libraries) == 0:
            self.report({'ERROR'}, "No asset library path defined")
            return {'CANCELLED'}
        
        asset_folder_path = asset_libraries[0].path
        if not os.path.isdir(asset_folder_path):
            self.report({'ERROR'}, "Asset library path does not exist")
            return {'CANCELLED'}

        selected_obj = context.active_object
        if not selected_obj:
            self.report({'ERROR'}, "No object selected")
            return {'CANCELLED'}
        
        base_name = bpy.path.clean_name(selected_obj.name)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_filename = f"{base_name}_{timestamp}.glb"
        destination = os.path.join(asset_folder_path, unique_filename)

        try:
            bpy.ops.export_scene.gltf(
                filepath=destination,
                use_selection=True,
                export_format='GLB'
            )
            self.report({'INFO'}, f"Uploaded as {unique_filename}")
        except Exception as e:
            self.report({'ERROR'}, f"Upload failed: {e}")

        return {'FINISHED'}

# ============= QUICK SHORTCUTS OPERATORS =============
class UNIFIED_OT_rename_objects(bpy.types.Operator):
    bl_label = "Rename Objects"
    bl_idname = "unified.rename_objects"
    bl_description = "Rename objects with mesh- prefix"
    
    def execute(self, context):
        rename_objects(selected_only=context.scene.rename_selected_only)
        self.report({'INFO'}, "Renamed objects")
        return {'FINISHED'}

class UNIFIED_OT_rename_materials(bpy.types.Operator):
    bl_label = "Rename Materials"
    bl_idname = "unified.rename_materials"
    bl_description = "Rename materials with mat- prefix"
    
    def execute(self, context):
        rename_materials(selected_only=context.scene.rename_selected_only)
        self.report({'INFO'}, "Renamed materials")
        return {'FINISHED'}

class UNIFIED_OT_resize_textures_1024(bpy.types.Operator):
    bl_label = "Resize Textures to 1024x1024"
    bl_idname = "unified.resize_textures_1024"
    bl_description = "Resize textures in selected objects"
    
    def execute(self, context):
        resize_textures_in_selected_objects((1024, 1024))
        self.report({'INFO'}, "Resized textures to 1024x1024")
        return {'FINISHED'}

class UNIFIED_OT_resize_textures_512(bpy.types.Operator):
    bl_label = "Resize Textures to 512x512"
    bl_idname = "unified.resize_textures_512"
    bl_description = "Resize textures in selected objects"
    
    def execute(self, context):
        resize_textures_in_selected_objects((512, 512))
        self.report({'INFO'}, "Resized textures to 512x512")
        return {'FINISHED'}

# ============= PHOTOSHOP INTEGRATION OPERATORS =============
class PS_OT_export_uv_layout(bpy.types.Operator):
    bl_idname = "ps.export_uv_layout"
    bl_label = "Export UV Layout"
    bl_description = "Export UV layout as PNG for texture painting reference"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "Select a mesh object!")
            return {'CANCELLED'}
        
        prefs = context.preferences.addons[__name__].preferences
        export_dir = prefs.texture_export_dir
        os.makedirs(export_dir, exist_ok=True)
        
        filename = f"{obj.name}_UV_Layout.png"
        filepath = os.path.join(export_dir, filename)
        
        bpy.ops.uv.export_layout(
            filepath=filepath,
            export_all=True,
            modified=False,
            mode='PNG',
            size=(2048, 2048),
            opacity=0.25
        )
        
        self.report({'INFO'}, f"UV layout exported: {filename}")
        return {'FINISHED'}

class PS_OT_export_render_reference(bpy.types.Operator):
    bl_idname = "ps.export_render_reference"
    bl_label = "Export Render Reference"
    bl_description = "Export render (Cycles GPU, 100 samples, denoised)"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        obj = context.active_object
        if not obj:
            self.report({'ERROR'}, "Select an object!")
            return {'CANCELLED'}
        
        prefs = context.preferences.addons[__name__].preferences
        export_dir = prefs.texture_export_dir
        os.makedirs(export_dir, exist_ok=True)
        
        scene = context.scene
        cycles_prefs = context.preferences.addons['cycles'].preferences if 'cycles' in context.preferences.addons else None
        
        # Save settings
        original_engine = scene.render.engine
        original_filepath = scene.render.filepath
        original_resolution_x = scene.render.resolution_x
        original_resolution_y = scene.render.resolution_y
        original_samples = scene.cycles.samples if hasattr(scene, 'cycles') else None
        original_use_denoising = scene.cycles.use_denoising if hasattr(scene, 'cycles') else None
        original_denoiser = scene.cycles.denoiser if hasattr(scene, 'cycles') else None
        original_device = scene.cycles.device if hasattr(scene, 'cycles') else None
        
        # Set render settings
        scene.render.engine = 'CYCLES'
        filename = f"{obj.name}_Reference.png"
        filepath = os.path.join(export_dir, filename)
        scene.render.filepath = filepath
        scene.render.resolution_x = 2048
        scene.render.resolution_y = 2048
        scene.cycles.samples = 100
        scene.cycles.use_denoising = True
        scene.cycles.denoiser = 'OPENIMAGEDENOISE'
        
        # GPU setup
        device_type = 'CPU'
        if cycles_prefs and prefs.use_gpu_render:
            compute_device_type = cycles_prefs.compute_device_type
            if compute_device_type != 'NONE':
                for device in cycles_prefs.get_devices_for_type(compute_device_type):
                    device.use = True
                scene.cycles.device = 'GPU'
                device_type = compute_device_type
        
        context.window.cursor_modal_set('WAIT')
        self.report({'INFO'}, f"⏳ Rendering... ({device_type}, 100 samples)")
        
        for area in context.screen.areas:
            area.tag_redraw()
        
        try:
            bpy.ops.render.render(write_still=True)
            
            # Restore settings
            scene.render.engine = original_engine
            scene.render.filepath = original_filepath
            scene.render.resolution_x = original_resolution_x
            scene.render.resolution_y = original_resolution_y
            if original_samples is not None:
                scene.cycles.samples = original_samples
            if original_use_denoising is not None:
                scene.cycles.use_denoising = original_use_denoising
            if original_denoiser is not None:
                scene.cycles.denoiser = original_denoiser
            if original_device is not None:
                scene.cycles.device = original_device
            
            self.report({'INFO'}, f"✓ Reference exported: {filename}")
        except Exception as e:
            self.report({'ERROR'}, f"Render failed: {str(e)}")
            return {'CANCELLED'}
        finally:
            context.window.cursor_modal_restore()
        
        return {'FINISHED'}

class PS_OT_open_in_photoshop(bpy.types.Operator):
    bl_idname = "ps.open_in_photoshop"
    bl_label = "Open in Photoshop"
    bl_description = "Open selected texture node in Photoshop (auto-saves to temp_data_ps)"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        context.window.cursor_modal_set('WAIT')
        
        try:
            obj = context.active_object
            if not obj or not obj.active_material or not obj.active_material.use_nodes:
                self.report({'ERROR'}, "No material with nodes!")
                return {'CANCELLED'}
            
            mat = obj.active_material
            selected_nodes = [n for n in mat.node_tree.nodes if n.select]
            if not selected_nodes:
                self.report({'ERROR'}, "No node selected in Shader Editor!")
                return {'CANCELLED'}
            
            image_node = None
            for node in selected_nodes:
                if node.type == 'TEX_IMAGE' and node.image:
                    image_node = node
                    break
            
            if not image_node:
                self.report({'ERROR'}, "Selected node is not an Image Texture!")
                return {'CANCELLED'}
            
            image = image_node.image
            
            # Auto-save to temp_data_ps
            if not image.filepath or image.is_dirty or not os.path.exists(bpy.path.abspath(image.filepath)):
                blend_filepath = bpy.data.filepath
                if not blend_filepath:
                    self.report({'ERROR'}, "Save your Blender file first!")
                    return {'CANCELLED'}
                
                blend_dir = os.path.dirname(bpy.path.abspath(blend_filepath))
                temp_dir = os.path.join(blend_dir, "temp_data_ps")
                os.makedirs(temp_dir, exist_ok=True)
                
                filename = bpy.path.clean_name(image.name)
                if not filename.endswith('.png'):
                    filename = f"{filename}.png"
                
                filepath = os.path.join(temp_dir, filename)
                image.filepath_raw = filepath
                image.file_format = 'PNG'
                image.save()
                self.report({'INFO'}, f"✓ Saved to: temp_data_ps/{filename}")
            
            filepath = bpy.path.abspath(image.filepath)
            if not os.path.exists(filepath):
                self.report({'ERROR'}, f"Image file not found!")
                return {'CANCELLED'}
            
            prefs = context.preferences.addons[__name__].preferences
            photoshop_path = prefs.photoshop_path
            
            if not photoshop_path or not os.path.exists(photoshop_path):
                self.report({'ERROR'}, "Photoshop path not set! Check preferences.")
                return {'CANCELLED'}
            
            subprocess.Popen([photoshop_path, filepath])
            self.report({'INFO'}, f"✓ Opened in Photoshop: {os.path.basename(filepath)}")
            
        except Exception as e:
            self.report({'ERROR'}, f"Failed: {str(e)}")
            return {'CANCELLED'}
        finally:
            context.window.cursor_modal_restore()
        
        return {'FINISHED'}

class PS_OT_import_textures_smart(bpy.types.Operator):
    bl_idname = "ps.import_textures_smart"
    bl_label = "Smart Import Textures"
    bl_description = "Import and auto-apply textures based on naming conventions"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        context.window.cursor_modal_set('WAIT')
        
        try:
            obj = context.active_object
            if not obj or obj.type != 'MESH':
                self.report({'ERROR'}, "Select a mesh object!")
                return {'CANCELLED'}
            
            self.report({'INFO'}, "🔍 Scanning for textures...")
            
            prefs = context.preferences.addons[__name__].preferences
            import_dir = prefs.texture_import_dir
            
            if not os.path.exists(import_dir):
                self.report({'ERROR'}, f"Import directory not found!")
                return {'CANCELLED'}
            
            if not obj.active_material:
                mat = bpy.data.materials.new(name=f"{obj.name}_Material")
                if obj.data.materials:
                    obj.data.materials[0] = mat
                else:
                    obj.data.materials.append(mat)
            else:
                mat = obj.active_material
            
            if not mat.use_nodes:
                mat.use_nodes = True
            
            bsdf = get_or_create_principled_bsdf(mat)
            nodes = mat.node_tree.nodes
            links = mat.node_tree.links
            
            formats = prefs.supported_formats.split(',')
            texture_files = []
            
            for file in os.listdir(import_dir):
                ext = file.split('.')[-1].lower()
                if ext in formats:
                    if obj.name.lower() in file.lower() or len(os.listdir(import_dir)) < 10:
                        texture_files.append(file)
            
            if not texture_files:
                self.report({'WARNING'}, "No matching texture files found")
                return {'CANCELLED'}
            
            imported_count = 0
            y_offset = 0
            
            for tex_file in texture_files:
                filepath = os.path.join(import_dir, tex_file)
                tex_type = detect_texture_type(tex_file)
                
                if not tex_type:
                    continue
                
                if tex_file in bpy.data.images:
                    img = bpy.data.images[tex_file]
                    img.reload()
                else:
                    img = bpy.data.images.load(filepath)
                
                tex_node = nodes.new('ShaderNodeTexImage')
                tex_node.image = img
                tex_node.location = (-400, y_offset)
                tex_node.label = tex_type.replace('_', ' ').title()
                y_offset -= 300
                
                if tex_type == 'base_color':
                    links.new(tex_node.outputs['Color'], bsdf.inputs['Base Color'])
                elif tex_type == 'metallic':
                    links.new(tex_node.outputs['Color'], bsdf.inputs['Metallic'])
                elif tex_type == 'roughness':
                    links.new(tex_node.outputs['Color'], bsdf.inputs['Roughness'])
                elif tex_type == 'normal':
                    normal_node = nodes.new('ShaderNodeNormalMap')
                    normal_node.location = (-200, y_offset)
                    links.new(tex_node.outputs['Color'], normal_node.inputs['Color'])
                    links.new(normal_node.outputs['Normal'], bsdf.inputs['Normal'])
                    img.colorspace_settings.name = 'Non-Color'
                elif tex_type == 'height':
                    img.colorspace_settings.name = 'Non-Color'
                elif tex_type == 'emission':
                    links.new(tex_node.outputs['Color'], bsdf.inputs['Emission'])
                elif tex_type == 'alpha':
                    links.new(tex_node.outputs['Color'], bsdf.inputs['Alpha'])
                    mat.blend_method = 'BLEND'
                
                imported_count += 1
            
            self.report({'INFO'}, f"✓ Imported {imported_count} textures to {mat.name}")
        except Exception as e:
            self.report({'ERROR'}, f"Import failed: {str(e)}")
            return {'CANCELLED'}
        finally:
            context.window.cursor_modal_restore()
        
        return {'FINISHED'}

class PS_OT_reload_all_textures(bpy.types.Operator):
    bl_idname = "ps.reload_all_textures"
    bl_label = "Reload All Textures"
    bl_description = "Reload all image textures in the scene"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        reloaded = 0
        for img in bpy.data.images:
            if img.source == 'FILE' and img.filepath:
                try:
                    img.reload()
                    reloaded += 1
                except:
                    pass
        
        self.report({'INFO'}, f"Reloaded {reloaded} textures")
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
        return {'FINISHED'}

class PS_OT_open_texture_folder(bpy.types.Operator):
    bl_idname = "ps.open_texture_folder"
    bl_label = "Open Texture Folder"
    bl_description = "Open texture folder in file explorer"
    
    folder_type: bpy.props.EnumProperty(
        items=[
            ('IMPORT', 'Import', 'Import folder'),
            ('EXPORT', 'Export', 'Export folder'),
        ]
    )
    
    def execute(self, context):
        prefs = context.preferences.addons[__name__].preferences
        folder = prefs.texture_import_dir if self.folder_type == 'IMPORT' else prefs.texture_export_dir
        os.makedirs(folder, exist_ok=True)
        
        system = platform.system()
        if system == 'Windows':
            os.startfile(folder)
        elif system == 'Darwin':
            subprocess.Popen(['open', folder])
        else:
            subprocess.Popen(['xdg-open', folder])
        return {'FINISHED'}

# ============= SUBSTANCE PAINTER INTEGRATION OPERATORS =============
class SP_OT_export_glb(bpy.types.Operator):
    bl_idname = "sp.export_glb"
    bl_label = "Export for Substance"
    bl_description = "Export selected object as GLB for Substance Painter"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        if not context.selected_objects:
            self.report({'WARNING'}, "No object selected!")
            return {'CANCELLED'}
        
        prefs = context.preferences.addons[__name__].preferences
        export_dir = prefs.substance_export_dir
        
        try:
            if not os.path.exists(export_dir):
                os.makedirs(export_dir)
        except Exception as e:
            self.report({'ERROR'}, f"Cannot create directory: {str(e)}")
            return {'CANCELLED'}
        
        filepath = os.path.join(export_dir, prefs.substance_export_filename)
        
        try:
            bpy.ops.export_scene.gltf('EXEC_DEFAULT', filepath=filepath, export_format='GLB', use_selection=True)
            self.report({'INFO'}, f"Exported: {prefs.substance_export_filename}")
        except Exception as e:
            self.report({'ERROR'}, f"Export failed: {str(e)}")
            return {'CANCELLED'}
        
        return {'FINISHED'}

class SP_OT_open_substance(bpy.types.Operator):
    bl_idname = "sp.open_substance"
    bl_label = "Open in Substance"
    bl_description = "Open exported file in Substance Painter"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        prefs = context.preferences.addons[__name__].preferences
        substance_path = prefs.substance_painter_path
        export_dir = prefs.substance_export_dir
        glb_path = os.path.join(export_dir, prefs.substance_export_filename)
        
        if not os.path.exists(glb_path):
            self.report({'WARNING'}, "GLB file not found! Export first.")
            return {'CANCELLED'}
        
        if not os.path.exists(substance_path):
            self.report({'ERROR'}, "Substance Painter not found! Check preferences.")
            return {'CANCELLED'}
        
        try:
            glb_path = os.path.abspath(glb_path).replace('/', '\\')
            cmd = [substance_path, "--mesh", glb_path]
            subprocess.Popen(cmd)
            self.report({'INFO'}, f"Opening Substance Painter...")
        except Exception as e:
            self.report({'ERROR'}, f"Failed: {str(e)}")
            return {'CANCELLED'}
        
        return {'FINISHED'}

class SP_OT_import_glb(bpy.types.Operator, ImportHelper):
    bl_idname = "sp.import_glb"
    bl_label = "Import from Substance"
    bl_description = "Browse and import GLB from Substance Painter"
    bl_options = {'REGISTER', 'UNDO'}
    
    filename_ext = ".glb"
    filter_glob: bpy.props.StringProperty(default="*.glb", options={'HIDDEN'})
    
    def invoke(self, context, event):
        prefs = context.preferences.addons[__name__].preferences
        if os.path.exists(prefs.substance_import_dir):
            self.filepath = prefs.substance_import_dir
        return super().invoke(context, event)
    
    def execute(self, context):
        if not os.path.exists(self.filepath):
            self.report({'WARNING'}, f"File not found!")
            return {'CANCELLED'}
        
        try:
            bpy.ops.import_scene.gltf('EXEC_DEFAULT', filepath=self.filepath)
            self.report({'INFO'}, f"Imported: {os.path.basename(self.filepath)}")
        except Exception as e:
            self.report({'ERROR'}, f"Import failed: {str(e)}")
            return {'CANCELLED'}
        
        return {'FINISHED'}

class SP_OT_import_latest(bpy.types.Operator):
    bl_idname = "sp.import_latest"
    bl_label = "Import Latest"
    bl_description = "Import most recent GLB from Substance"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        prefs = context.preferences.addons[__name__].preferences
        import_dir = prefs.substance_import_dir
        
        if not os.path.exists(import_dir):
            self.report({'WARNING'}, f"Import directory not found!")
            return {'CANCELLED'}
        
        glb_files = [os.path.join(import_dir, f) for f in os.listdir(import_dir) if f.endswith('.glb')]
        
        if not glb_files:
            self.report({'WARNING'}, f"No GLB files found!")
            return {'CANCELLED'}
        
        latest_file = max(glb_files, key=os.path.getmtime)
        
        try:
            bpy.ops.import_scene.gltf('EXEC_DEFAULT', filepath=latest_file)
            self.report({'INFO'}, f"Imported: {os.path.basename(latest_file)}")
        except Exception as e:
            self.report({'ERROR'}, f"Import failed: {str(e)}")
            return {'CANCELLED'}
        
        return {'FINISHED'}

class SP_OT_cleanup_unused(bpy.types.Operator):
    bl_idname = "sp.cleanup_unused"
    bl_label = "Clean Up Unused Data"
    bl_description = "Remove unused images and materials"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        def count_orphans():
            return sum([
                len([img for img in bpy.data.images if img.users == 0]),
                len([mat for mat in bpy.data.materials if mat.users == 0]),
                len([mesh for mesh in bpy.data.meshes if mesh.users == 0]),
                len([tex for tex in bpy.data.textures if tex.users == 0])
            ])
        
        initial_orphans = count_orphans()
        
        for i in range(5):
            before = count_orphans()
            bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
            after = count_orphans()
            if before == after:
                break
        
        cleared = initial_orphans - count_orphans()
        
        if cleared > 0:
            self.report({'INFO'}, f"Cleared {cleared} unused data blocks")
        else:
            self.report({'INFO'}, "No unused data found")
        
        return {'FINISHED'}

# ============= SPELL CHECKING OPERATORS =============
class UNIFIED_OT_spell_check_now(bpy.types.Operator):
    bl_idname = "unified.spell_check_now"
    bl_label = "Check Spelling Now"
    bl_description = "Check all label descriptions for spelling errors"

    def execute(self, context):
        scene = context.scene
        results = {}
        label_objs = [obj for obj in bpy.data.objects if obj.name.startswith("label-") and "dot_label_data" in obj]
        for obj in label_objs:
            desc = obj["dot_label_data"].get("description", "")
            errors = []
            if scene.spelling_spotter_enabled and desc:
                try:
                    errors = check_spelling_languagetool(desc)
                except Exception as e:
                    errors = [("API error", [str(e)])]
            results[obj.name] = errors
        set_spell_cache(scene, results)
        self.report({'INFO'}, f"Spellcheck complete for {len(label_objs)} labels")
        return {'FINISHED'}

class UNIFIED_OT_toggle_ignore_issue(bpy.types.Operator):
    bl_idname = "unified.toggle_ignore_issue"
    bl_label = "Toggle Ignore Issue"
    bl_description = "Toggle ignore for this spelling issue"

    object_name: bpy.props.StringProperty()
    issue: bpy.props.StringProperty()

    def execute(self, context):
        obj = bpy.data.objects.get(self.object_name)
        if obj is not None:
            ignore_list = list(obj.get("spelling_ignore", []))
            if self.issue in ignore_list:
                ignore_list.remove(self.issue)
            else:
                ignore_list.append(self.issue)
            obj["spelling_ignore"] = ignore_list
            return {'FINISHED'}
        else:
            self.report({'ERROR'}, "Object not found")
            return {'CANCELLED'}

class UNIFIED_OT_edit_properties_helper(bpy.types.Operator):
    bl_idname = "unified.edit_properties_helper"
    bl_label = "Edit Properties (Helper)"
    bl_description = "Set object active and open Edit Properties dialog"

    object_name: bpy.props.StringProperty()

    def execute(self, context):
        obj = bpy.data.objects.get(self.object_name)
        if obj:
            context.view_layer.objects.active = obj
            obj.select_set(True)
            bpy.ops.unified.edit_properties('INVOKE_DEFAULT')
            return {'FINISHED'}
        else:
            self.report({'ERROR'}, f"Object '{self.object_name}' not found")
            return {'CANCELLED'}

# ============= PANELS =============
class UNIFIED_PT_main_panel(bpy.types.Panel):
    bl_label = "LP Toolkit ULTIMATE"
    bl_idname = "UNIFIED_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'LP Toolkit'

    def draw(self, context):
        layout = self.layout
        layout.label(text="LP Toolkit by Aman", icon='TOOL_SETTINGS')
        layout.label(text="v4.0.0 - ULTIMATE Edition")
        layout.separator()
        layout.operator("unified.open_preferences", text="⚙ Settings", icon='PREFERENCES')

class UNIFIED_PT_labels_panel(bpy.types.Panel):
    bl_label = "Labels & Animation"
    bl_idname = "UNIFIED_PT_labels_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'LP Toolkit'
    bl_parent_id = "UNIFIED_PT_main_panel"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        obj = context.active_object

        # Create Labels
        layout.operator("unified.create_label", text="Create New Label")
        layout.operator("unified.quick_create_label", text="Quick Create (Ctrl+Shift+Q)")
        
        layout.separator()
        
        # Selected Label Info
        if obj and (obj.name.startswith("dot-") or obj.name.startswith("label-")):
            layout.label(text="Selected Label:")
            
            if "dot_label_data" in obj:
                description = obj["dot_label_data"].get("description", "No description")
                animdata = obj["dot_label_data"].get("animdata", "No animation data")
                layout.label(text=f"Desc: {description[:30]}...")
                layout.label(text=f"Anim: {animdata}")
            
            if obj.data:
                layout.label(text=f"Mesh: {obj.data.name}")
            
            layout.operator("unified.edit_properties", text="Edit Properties")
            layout.separator()

        # Import/Export
        layout.label(text="Import/Export:")
        layout.operator("unified.import_data", text="Import (JSON)")
        layout.operator("unified.export_data", text="Export (HTML/JSON)")
        
        # Export GLB with settings
        box = layout.box()
        box.label(text="GLB Export Settings:", icon='EXPORT')
        box.prop(context.scene, "export_frame_range_enabled", text="Use Frame Range")
        box.prop(context.scene, "export_nla_combined", text="Combine NLA Tracks")
        box.operator("unified.export_glb", text="Export GLB", icon='FILE_3D')
        
        layout.separator()

        # Animation Tools
        layout.label(text="Animation Tools:")
        
        # Diagnostic tools (highlighted)
        box = layout.box()
        box.label(text="🔍 Pre-Export Check:", icon='INFO')
        box.operator("unified.diagnose_animation", text="Diagnose Animation", icon='VIEWZOOM')
        box.operator("unified.fix_animation_range", text="Fix Animation Range", icon='CHECKMARK')
        
        layout.separator()
        
        layout.operator("unified.shift_animation", text="Shift Animation")
        layout.operator("unified.add_timeline_markers", text="Add Markers")
        layout.operator("unified.sync_markers_to_data", text="Sync Markers")
        layout.operator("unified.remove_all_markers", text="Clear Markers")

class UNIFIED_PT_asset_library_panel(bpy.types.Panel):
    bl_label = "Asset Library"
    bl_idname = "UNIFIED_PT_asset_library_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'LP Toolkit'
    bl_parent_id = "UNIFIED_PT_main_panel"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.prop(scene, "glb_search_query", text="Search", icon='VIEWZOOM')
        layout.operator("unified.search_glb_files", text="Search GLB Files", icon='FILE_REFRESH')

        layout.separator()
        layout.label(text="Results:", icon='PRESET')
        
        if scene.glb_file_results:
            for result in scene.glb_file_results:
                file_name = os.path.basename(result.file_path)
                row = layout.row()
                row.label(text=file_name[:25], icon='FILE')
                op = row.operator("unified.import_glb_file", text="", icon='IMPORT')
                op.filepath = result.file_path
        else:
            layout.label(text="No files found")

        layout.separator()
        layout.operator("unified.upload_glb_file", text="Upload Selected", icon='EXPORT')

class UNIFIED_PT_quick_shortcuts_panel(bpy.types.Panel):
    bl_label = "Quick Shortcuts"
    bl_idname = "UNIFIED_PT_quick_shortcuts_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'LP Toolkit'
    bl_parent_id = "UNIFIED_PT_main_panel"
    bl_options = {'DEFAULT_CLOSED'}
    
    def draw(self, context):
        layout = self.layout

        layout.prop(context.scene, "rename_selected_only", icon='RESTRICT_SELECT_OFF')
        
        layout.separator()
        layout.label(text="Rename:", icon='OUTLINER_OB_FONT')
        layout.operator("unified.rename_objects", text="Objects", icon='OBJECT_DATA')
        layout.operator("unified.rename_materials", text="Materials", icon='MATERIAL')
        
        layout.separator()
        layout.label(text="Resize Textures:", icon='IMAGE_DATA')
        layout.operator("unified.resize_textures_1024", text="1024x1024", icon='TEXTURE')
        layout.operator("unified.resize_textures_512", text="512x512", icon='TEXTURE')

class UNIFIED_PT_spell_check_panel(bpy.types.Panel):
    bl_label = "Spell Checker"
    bl_idname = "UNIFIED_PT_spell_check_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'LP Toolkit'
    bl_parent_id = "UNIFIED_PT_main_panel"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        layout.prop(scene, "spelling_spotter_enabled", toggle=True, icon='CHECKMARK')
        layout.operator("unified.spell_check_now", icon='FILE_REFRESH')
        
        cache = get_spell_cache(scene)
        if cache['timestamp']:
            layout.label(text=f"Last: {cache['timestamp']}", icon='TIME')
        
        label_objs = [obj for obj in bpy.data.objects if obj.name.startswith("label-") and "dot_label_data" in obj]
        if not label_objs:
            layout.label(text="No labels found")
            return
        
        for obj in label_objs:
            desc_label = obj["dot_label_data"].get("description", "").strip()
            if not desc_label:
                desc_label = "(No Description)"
            
            display_label = f"{desc_label}  [{obj.name}]"
            
            errors = cache['results'].get(obj.name, []) if scene.spelling_spotter_enabled else []
            box = layout.box()
            
            # Header row with label name and edit button
            row = box.row(align=True)
            
            ignore_list = list(obj.get("spelling_ignore", []))
            non_ignored_issues = [word for word, _ in errors if word not in ignore_list]
            
            if scene.spelling_spotter_enabled and errors and non_ignored_issues:
                row.label(text=f"{display_label}", icon='ERROR')
            else:
                row.label(text=display_label, icon='CHECKMARK')
            
            # Edit button
            op = row.operator("unified.edit_properties_helper", text="", icon='PREFERENCES', emboss=False)
            op.object_name = obj.name
            
            # Show description field
            row = box.row()
            row.prop(obj, '["dot_label_data"]["description"]', text="Description")
            
            # Show spelling issues
            if scene.spelling_spotter_enabled and errors:
                for word, suggestions in errors:
                    is_ignored = word in ignore_list
                    if is_ignored:
                        # Only show untick icon for ignored issues
                        row2 = box.row(align=True)
                        op3 = row2.operator("unified.toggle_ignore_issue", text="", icon='CHECKBOX_HLT', emboss=False)
                        op3.object_name = obj.name
                        op3.issue = word
                        continue
                    
                    issue_text = f"Issue: '{word}' | Suggestions: {', '.join(suggestions) if suggestions else 'None'}"
                    row2 = box.row(align=True)
                    row2.label(text=issue_text, icon='INFO')
                    op3 = row2.operator("unified.toggle_ignore_issue", text="", icon='CHECKBOX_DEHLT', emboss=False)
                    op3.object_name = obj.name
                    op3.issue = word

# ============= PHOTOSHOP INTEGRATION PANEL =============
class UNIFIED_PT_photoshop_panel(bpy.types.Panel):
    bl_label = "Paint with Photoshop"
    bl_idname = "UNIFIED_PT_photoshop_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'LP Toolkit'
    bl_parent_id = "UNIFIED_PT_main_panel"
    bl_options = {'DEFAULT_CLOSED'}
    
    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        prefs = context.preferences.addons[__name__].preferences
        
        # Object Info
        box = layout.box()
        if obj and obj.type == 'MESH':
            box.label(text=f"Active: {obj.name}", icon='OBJECT_DATA')
            if obj.active_material:
                box.label(text=f"Material: {obj.active_material.name}", icon='MATERIAL')
        else:
            box.label(text="No mesh selected", icon='ERROR')
        
        # Export
        export_box = layout.box()
        export_box.label(text="Export for Painting:", icon='EXPORT')
        if obj and obj.type == 'MESH':
            export_box.operator("ps.export_uv_layout", icon='UV')
            export_box.operator("ps.export_render_reference", icon='RENDER_STILL')
        else:
            row = export_box.row()
            row.enabled = False
            row.label(text="Select mesh object")
        
        row = export_box.row()
        op = row.operator("ps.open_texture_folder", text="Open Export Folder", icon='FILEBROWSER')
        op.folder_type = 'EXPORT'
        
        # Import
        import_box = layout.box()
        import_box.label(text="Import Textures:", icon='IMPORT')
        import_dir_exists = os.path.exists(prefs.texture_import_dir)
        
        if obj and obj.type == 'MESH' and import_dir_exists:
            import_box.operator("ps.import_textures_smart", text="Smart Import", icon='AUTO')
        else:
            row = import_box.row()
            row.enabled = False
            if not import_dir_exists:
                row.label(text="Import folder not found")
            else:
                row.label(text="Select mesh object")
        
        row = import_box.row()
        op = row.operator("ps.open_texture_folder", text="Open Import Folder", icon='FILEBROWSER')
        op.folder_type = 'IMPORT'
        
        # Photoshop Integration
        ps_box = layout.box()
        ps_box.label(text="Photoshop Integration:", icon='IMAGE_DATA')
        ps_exists = os.path.exists(prefs.photoshop_path)
        
        node_selected = False
        if obj and obj.active_material and obj.active_material.use_nodes:
            selected_nodes = [n for n in obj.active_material.node_tree.nodes if n.select]
            node_selected = any(n.type == 'TEX_IMAGE' and n.image for n in selected_nodes)
        
        if ps_exists and node_selected:
            ps_box.operator("ps.open_in_photoshop", text="Open in Photoshop", icon='PLAY')
            ps_box.label(text="(Auto-saves to temp_data_ps)", icon='INFO')
        else:
            row = ps_box.row()
            row.enabled = False
            if not ps_exists:
                row.label(text="Set Photoshop path in settings")
            else:
                row.label(text="Select Image Texture node")
        
        # Utilities
        utils_box = layout.box()
        utils_box.label(text="Utilities:", icon='TOOL_SETTINGS')
        utils_box.operator("ps.reload_all_textures", icon='FILE_REFRESH')
        
        # Status info
        if import_dir_exists:
            formats = prefs.supported_formats.split(',')
            try:
                file_count = sum(1 for f in os.listdir(prefs.texture_import_dir) 
                               if f.split('.')[-1].lower() in formats)
                if file_count > 0:
                    layout.label(text=f"{file_count} texture files in import folder", icon='INFO')
            except:
                pass

# ============= SUBSTANCE PAINTER INTEGRATION PANEL =============
class UNIFIED_PT_substance_panel(bpy.types.Panel):
    bl_label = "Paint with Substance"
    bl_idname = "UNIFIED_PT_substance_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'LP Toolkit'
    bl_parent_id = "UNIFIED_PT_main_panel"
    bl_options = {'DEFAULT_CLOSED'}
    
    def draw(self, context):
        layout = self.layout
        prefs = context.preferences.addons[__name__].preferences
        
        # Export
        export_box = layout.box()
        export_box.label(text="Export to Substance:", icon='EXPORT')
        
        if context.selected_objects:
            export_box.operator("sp.export_glb", text="Export Selected", icon='OBJECT_DATA')
        else:
            row = export_box.row()
            row.enabled = False
            row.operator("sp.export_glb", text="No Selection", icon='ERROR')
        
        # Open in Substance
        open_box = layout.box()
        open_box.label(text="Open in Substance:", icon='FILE_TICK')
        
        glb_exists = os.path.exists(os.path.join(prefs.substance_export_dir, prefs.substance_export_filename))
        sp_exists = os.path.exists(prefs.substance_painter_path)
        
        if glb_exists and sp_exists:
            open_box.operator("sp.open_substance", icon='PLAY')
        else:
            row = open_box.row()
            row.enabled = False
            if not glb_exists:
                row.label(text="No GLB file - export first")
            else:
                row.label(text="Substance not found - check settings")
        
        # Import
        import_box = layout.box()
        import_box.label(text="Import from Substance:", icon='IMPORT')
        import_box.operator("sp.import_latest", text="Import Latest", icon='TIME')
        import_box.operator("sp.import_glb", text="Browse & Import", icon='FILEBROWSER')
        
        # Cleanup
        cleanup_box = layout.box()
        cleanup_box.label(text="Cleanup:", icon='BRUSH_DATA')
        cleanup_box.operator("sp.cleanup_unused", icon='TRASH')

# ============= 3D VIEWER IPR (INTERACTIVE PREVIEW RENDERING) =============

class VIEWER_OT_ipr_start(bpy.types.Operator):
    """Export GLB temporarily and launch local server for live preview"""
    bl_idname = "viewer.ipr_start"
    bl_label = "Start IPR Preview"
    bl_description = "Export model to temp folder, launch local HTTP server, and open viewer"
    
    re_export: bpy.props.BoolProperty(
        name="Re-export GLB",
        description="Export fresh GLB before launching (recommended)",
        default=True
    )
    
    export_audio: bpy.props.BoolProperty(
        name="Export Audio",
        description="Look for and export audio files",
        default=False
    )
    
    def invoke(self, context, event):
        # Show dialog with options
        return context.window_manager.invoke_props_dialog(self)
    
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "re_export", text="Re-export Fresh GLB + JSON")
        layout.prop(self, "export_audio", text="Include Audio Files")
        layout.label(text="💡 Re-export ensures latest changes", icon='INFO')
    
    def execute(self, context):
        # Get HTML viewer path from preferences
        prefs = context.preferences.addons[__name__].preferences
        if not hasattr(prefs, 'viewer_html_path') or not prefs.viewer_html_path:
            self.report({'ERROR'}, "Set viewer HTML path in addon preferences first")
            return {'CANCELLED'}
        
        viewer_html_path = prefs.viewer_html_path
        if not os.path.isfile(viewer_html_path):
            self.report({'ERROR'}, "Viewer HTML file not found")
            return {'CANCELLED'}
        
        viewer_dir = os.path.dirname(viewer_html_path)
        
        # Check if blend file is saved
        blend_file = bpy.data.filepath
        if not blend_file:
            self.report({'ERROR'}, "Save your .blend file first")
            return {'CANCELLED'}
        
        blend_name = os.path.splitext(os.path.basename(blend_file))[0]
        
        try:
            # Create temp directory for IPR
            temp_dir = tempfile.mkdtemp(prefix=f"blender_ipr_{blend_name}_")
            print(f"📁 IPR temp directory: {temp_dir}")
            
            # Export GLB to temp (if re-export is enabled)
            glb_path = os.path.join(temp_dir, f"{blend_name}.glb")
            
            if self.re_export:
                print(f"🔄 Re-exporting fresh GLB with Aman2 preset...")
                # Use COMPLETE Aman2 preset settings (all 100+ parameters)
                bpy.ops.export_scene.gltf(
                    filepath=glb_path,
                    export_import_convert_lighting_mode='SPEC',
                    gltf_export_id='',
                    export_use_gltfpack=False,
                    export_gltfpack_tc=True,
                    export_gltfpack_tq=8,
                    export_gltfpack_si=1.0,
                    export_gltfpack_sa=False,
                    export_gltfpack_slb=False,
                    export_gltfpack_vp=14,
                    export_gltfpack_vt=12,
                    export_gltfpack_vn=8,
                    export_gltfpack_vc=8,
                    export_gltfpack_vpi='Integer',
                    export_gltfpack_noq=True,
                    # export_gltfpack_kn=False,  # ❌ Removed - not available in all Blender versions
                    export_format='GLB',
                    export_copyright='',
                    export_image_format='AUTO',
                    export_image_add_webp=False,
                    export_image_webp_fallback=False,
                    export_texture_dir='',
                    export_jpeg_quality=75,
                    export_image_quality=75,
                    export_keep_originals=False,
                    export_texcoords=True,
                    export_normals=True,
                    export_gn_mesh=False,
                    export_draco_mesh_compression_enable=False,
                    export_draco_mesh_compression_level=6,
                    export_draco_position_quantization=14,
                    export_draco_normal_quantization=10,
                    export_draco_texcoord_quantization=12,
                    export_draco_color_quantization=10,
                    export_draco_generic_quantization=12,
                    export_tangents=False,
                    export_materials='EXPORT',
                    export_unused_images=False,
                    export_unused_textures=False,
                    export_vertex_color='MATERIAL',
                    export_all_vertex_colors=True,
                    export_active_vertex_color_when_no_material=True,
                    export_attributes=False,
                    use_mesh_edges=False,
                    use_mesh_vertices=False,
                    export_cameras=False,
                    use_selection=False,
                    use_visible=True,
                    use_renderable=False,
                    use_active_collection_with_nested=True,
                    use_active_collection=False,
                    use_active_scene=False,
                    collection='',
                    at_collection_center=False,
                    export_extras=True,
                    export_yup=True,
                    export_apply=False,
                    export_shared_accessors=False,
                    export_animations=True,
                    export_frame_range=True,  # ✅ Use scene timeline range!
                    export_frame_step=1,
                    export_force_sampling=True,
                    export_sampling_interpolation_fallback='LINEAR',
                    export_pointer_animation=False,
                    export_animation_mode='ACTIVE_ACTIONS',
                    export_nla_strips_merged_animation_name='Animation',
                    export_def_bones=False,
                    export_hierarchy_flatten_bones=False,
                    export_hierarchy_flatten_objs=False,
                    export_armature_object_remove=False,
                    export_leaf_bone=False,
                    export_optimize_animation_size=True,
                    export_optimize_animation_keep_anim_armature=True,
                    export_optimize_animation_keep_anim_object=False,
                    export_optimize_disable_viewport=False,
                    export_negative_frame='SLIDE',
                    export_anim_slide_to_zero=False,
                    export_bake_animation=True,
                    export_merge_animation='ACTION',
                    export_anim_single_armature=True,
                    export_reset_pose_bones=True,
                    export_current_frame=False,
                    export_rest_position_armature=True,
                    export_anim_scene_split_object=True,
                    export_skins=True,
                    export_influence_nb=4,
                    export_all_influences=False,
                    export_morph=True,
                    export_morph_normal=True,
                    export_morph_tangent=False,
                    export_morph_animation=True,
                    export_morph_reset_sk_data=True,
                    export_lights=False,
                    export_try_sparse_sk=True,
                    export_try_omit_sparse_sk=False,
                    export_gpu_instances=False,
                    export_action_filter=False,
                    export_convert_animation_pointer=False,
                    export_nla_strips=True,
                    export_original_specular=False,
                    export_hierarchy_full_collections=False,
                    export_extra_animations=False,
                )
                print(f"✅ Exported fresh GLB with Aman2 preset: {glb_path}")
            else:
                # Copy existing GLB from blend file directory
                export_folder = os.path.dirname(blend_file)
                source_glb = None
                for name in [f"{blend_name}.glb", f"{blend_name}.gltf"]:
                    test_path = os.path.join(export_folder, name)
                    if os.path.exists(test_path):
                        source_glb = test_path
                        break
                
                if source_glb:
                    shutil.copy2(source_glb, glb_path)
                    print(f"✅ Copied existing GLB: {os.path.basename(source_glb)}")
                else:
                    # No existing GLB, must export
                    self.report({'WARNING'}, "No existing GLB found, exporting new one...")
                    bpy.ops.export_scene.gltf(filepath=glb_path, export_format='GLB')
                    print(f"✅ Exported GLB: {glb_path}")
            
            # Handle labels JSON
            export_folder = os.path.dirname(blend_file)
            json_path = None
            
            # Copy existing JSON (simplified - use your existing JSON export if available)
            possible_json_names = [
                f"{blend_name}_dot_labels.json",
                f"{blend_name}_labels.json",
                f"{blend_name}.json",
            ]
            
            for json_name in possible_json_names:
                test_path = os.path.join(export_folder, json_name)
                if os.path.exists(test_path):
                    json_dest = os.path.join(temp_dir, json_name)
                    shutil.copy2(test_path, json_dest)
                    json_path = json_dest
                    print(f"✅ Copied JSON: {json_name}")
                    break
            
            # Handle audio files (if enabled)
            audio_path = None
            if self.export_audio:
                print(f"🎵 Processing audio...")
                
                # Check if there are audio strips in VSE
                has_audio_in_vse = False
                if context.scene.sequence_editor:
                    for seq in context.scene.sequence_editor.sequences_all:
                        if seq.type == 'SOUND':
                            has_audio_in_vse = True
                            break
                
                # Only render fresh audio if re_export is enabled AND VSE has audio
                if self.re_export and has_audio_in_vse:
                    # Render audio from VSE
                    audio_path = os.path.join(temp_dir, f"{blend_name}_audio.mp3")
                    try:
                        print(f"🎙️  Rendering fresh audio from VSE...")
                        bpy.ops.sound.mixdown(
                            filepath=audio_path,
                            codec='MP3',
                            format='MP3',
                            container='MP3',
                            bitrate=320,
                            accuracy=1024,
                            split_channels=False
                        )
                        print(f"✅ Rendered fresh audio from VSE: {blend_name}_audio.mp3")
                    except Exception as e:
                        print(f"⚠️  Audio render failed: {e}")
                        audio_path = None
                
                # If no fresh render, look for existing audio files
                if not audio_path:
                    print(f"🎵 Looking for existing audio files...")
                    possible_audio_names = [
                        f"{blend_name}_audio.mp3", f"{blend_name}_sound.mp3", f"{blend_name}.mp3",
                        f"{blend_name}_audio.wav", f"{blend_name}_sound.wav", f"{blend_name}.wav",
                        f"{blend_name}_audio.ogg", f"{blend_name}_sound.ogg", f"{blend_name}.ogg",
                        f"{blend_name}_audio.m4a", f"{blend_name}_sound.m4a", f"{blend_name}.m4a",
                    ]
                    
                    for audio_name in possible_audio_names:
                        test_path = os.path.join(export_folder, audio_name)
                        if os.path.exists(test_path):
                            audio_dest = os.path.join(temp_dir, audio_name)
                            shutil.copy2(test_path, audio_dest)
                            audio_path = audio_dest
                            print(f"✅ Copied existing audio: {audio_name}")
                            break
                    
                    if not audio_path:
                        if has_audio_in_vse and not self.re_export:
                            print(f"ℹ️  Enable 'Re-export' to render fresh audio from VSE")
                        else:
                            print(f"⚠️  No existing audio files found")
            
            # Copy viewer HTML and its directory contents to temp
            for item in os.listdir(viewer_dir):
                src_path = os.path.join(viewer_dir, item)
                dest_path = os.path.join(temp_dir, item)
                if os.path.isfile(src_path):
                    shutil.copy2(src_path, dest_path)
                elif os.path.isdir(src_path):
                    shutil.copytree(src_path, dest_path, dirs_exist_ok=True)
            
            print(f"✅ Copied viewer files")
            
            # Find available port
            port = 8000
            while port < 9000:
                try:
                    with socketserver.TCPServer(("", port), None) as test_server:
                        break
                except OSError:
                    port += 1
            
            # Create HTTP server with JSON upload support
            class Handler(http.server.SimpleHTTPRequestHandler):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, directory=temp_dir, **kwargs)
                
                def log_message(self, format, *args):
                    print(f"🌐 HTTP: {format % args}")
                
                def do_POST(self):
                    """Handle POST requests for JSON uploads"""
                    if self.path == '/upload-json':
                        try:
                            # Read content length
                            content_length = int(self.headers['Content-Length'])
                            post_data = self.rfile.read(content_length)
                            
                            # Parse JSON
                            json_data = json.loads(post_data.decode('utf-8'))
                            
                            # Get filename from headers or use default
                            filename = self.headers.get('X-Filename', f'{blend_name}_labels.json')
                            
                            # Save to temp directory
                            json_save_path = os.path.join(temp_dir, filename)
                            with open(json_save_path, 'w', encoding='utf-8') as f:
                                json.dump(json_data, f, indent=2)
                            
                            print(f"\n💾 ========== JSON UPLOADED TO IPR ==========")
                            print(f"📄 Filename: {filename}")
                            print(f"📍 Saved to: {json_save_path}")
                            print(f"📊 Labels: {len(json_data) if isinstance(json_data, list) else 1}")
                            print(f"=" * 45 + "\n")
                            
                            # Send success response
                            self.send_response(200)
                            self.send_header('Content-type', 'application/json')
                            self.send_header('Access-Control-Allow-Origin', '*')
                            self.end_headers()
                            response = json.dumps({'success': True, 'message': f'Saved {filename}'})
                            self.wfile.write(response.encode('utf-8'))
                            
                        except Exception as e:
                            print(f"❌ Upload error: {e}")
                            self.send_response(500)
                            self.send_header('Content-type', 'application/json')
                            self.send_header('Access-Control-Allow-Origin', '*')
                            self.end_headers()
                            response = json.dumps({'success': False, 'error': str(e)})
                            self.wfile.write(response.encode('utf-8'))
                    else:
                        self.send_error(404, "POST endpoint not found")
                
                def do_OPTIONS(self):
                    """Handle CORS preflight requests"""
                    self.send_response(200)
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
                    self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Filename')
                    self.end_headers()
            
            server = socketserver.TCPServer(("", port), Handler)
            
            # Start server in background thread
            def serve_forever():
                print(f"🚀 Local server started on port {port}")
                server.serve_forever()
            
            server_thread = threading.Thread(target=serve_forever, daemon=True)
            server_thread.start()
            
            # Store server state
            ipr_server_state['server'] = server
            ipr_server_state['thread'] = server_thread
            ipr_server_state['port'] = port
            ipr_server_state['temp_dir'] = temp_dir
            
            # Build URL
            viewer_filename = os.path.basename(viewer_html_path)
            url = f"http://localhost:{port}/{viewer_filename}#glb={blend_name}.glb"
            if json_path:
                json_filename = os.path.basename(json_path)
                url += f"&json={json_filename}"
            if audio_path:
                audio_filename = os.path.basename(audio_path)
                url += f"&audio={audio_filename}"
            
            print(f"🌐 Opening: {url}")
            
            # Open browser
            webbrowser.open(url, new=2)
            
            # Build success message
            parts = ["GLB"]
            if json_path:
                parts.append("JSON")
            if audio_path:
                parts.append("Audio")
            
            msg = f"✅ IPR running on port {port} ({' + '.join(parts)})"
            if self.re_export:
                msg += " [Fresh Export]"
            
            self.report({'INFO'}, msg)
            return {'FINISHED'}
            
        except Exception as e:
            print(f"❌ IPR Error: {e}")
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, f"IPR failed: {str(e)}")
            return {'CANCELLED'}


class VIEWER_OT_ipr_stop(bpy.types.Operator):
    """Stop the local IPR server"""
    bl_idname = "viewer.ipr_stop"
    bl_label = "Stop IPR Preview"
    bl_description = "Stop the local HTTP server and clean up temp files"
    
    def execute(self, context):
        if ipr_server_state['server']:
            try:
                ipr_server_state['server'].shutdown()
                ipr_server_state['server'].server_close()
                print(f"🛑 Server stopped on port {ipr_server_state['port']}")
                
                # Clean up temp directory
                if ipr_server_state['temp_dir'] and os.path.exists(ipr_server_state['temp_dir']):
                    shutil.rmtree(ipr_server_state['temp_dir'])
                    print(f"🗑️  Cleaned up temp dir: {ipr_server_state['temp_dir']}")
                
                # Reset state
                ipr_server_state['server'] = None
                ipr_server_state['thread'] = None
                ipr_server_state['port'] = None
                ipr_server_state['temp_dir'] = None
                
                self.report({'INFO'}, "IPR Preview stopped")
                return {'FINISHED'}
            except Exception as e:
                self.report({'ERROR'}, f"Error stopping server: {str(e)}")
                return {'CANCELLED'}
        else:
            self.report({'WARNING'}, "No IPR server running")
            return {'CANCELLED'}


class UNIFIED_PT_viewer_panel(bpy.types.Panel):
    """Panel for 3D Viewer IPR"""
    bl_label = "3D Viewer IPR"
    bl_idname = "UNIFIED_PT_viewer_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'LP Toolkit'
    bl_parent_id = "UNIFIED_PT_main_panel"
    bl_options = {'DEFAULT_CLOSED'}
    
    def draw(self, context):
        layout = self.layout
        prefs = context.preferences.addons[__name__].preferences
        
        # IPR Live Preview
        box = layout.box()
        box.label(text="IPR Live Preview", icon='VIEW_CAMERA')
        
        is_ipr_running = ipr_server_state['server'] is not None
        
        if is_ipr_running:
            col = box.column(align=True)
            col.scale_y = 1.3
            col.operator("viewer.ipr_stop", icon='CANCEL', text=f"⏹️ Stop IPR (Port {ipr_server_state['port']})")
            col.label(text="✅ Server Running", icon='CHECKMARK')
        else:
            col = box.column(align=True)
            col.scale_y = 1.3
            col.operator("viewer.ipr_start", icon='PLAY', text="🚀 Start IPR Preview")
        
        # Info about IPR
        info = box.column(align=True)
        info.scale_y = 0.7
        if not is_ipr_running:
            info.label(text="💡 Exports to temp & runs local server")
            info.label(text="   No file:// issues, works perfectly!")
        
        # IPR Tools (Fetch & Open Folder)
        layout.separator()
        tools_box = layout.box()
        tools_box.label(text="IPR Tools", icon='TOOL_SETTINGS')
        
        # Save GLB button
        row = tools_box.row()
        row.scale_y = 1.2
        if is_ipr_running and ipr_server_state['temp_dir']:
            row.operator("unified.save_ipr_glb", text="💾 Save GLB to Project", icon='EXPORT')
        else:
            row.operator("unified.save_ipr_glb", text="💾 Save GLB to Project (IPR not running)", icon='EXPORT')
            row.enabled = False
        
        # Fetch from IPR button
        row = tools_box.row()
        if is_ipr_running and ipr_server_state['temp_dir']:
            row.operator("unified.fetch_from_ipr", text="🔄 Fetch Label Updates", icon='WORLD')
        else:
            row.operator("unified.fetch_from_ipr", text="🔄 Fetch Label Updates (IPR not running)", icon='WORLD')
            row.enabled = False
        
        # Open IPR Folder button
        if is_ipr_running and ipr_server_state['temp_dir']:
            tools_box.operator("unified.open_ipr_folder", text="📂 Open IPR Folder", icon='FILE_FOLDER')
        
        # Settings
        layout.separator()
        settings_box = layout.box()
        settings_box.label(text="Settings", icon='PREFERENCES')
        
        if hasattr(prefs, 'viewer_html_path'):
            settings_box.prop(prefs, "viewer_html_path", text="HTML Path")
            
            # Show status
            if prefs.viewer_html_path:
                viewer_path = os.path.normpath(os.path.expanduser(prefs.viewer_html_path))
                if os.path.isfile(viewer_path):
                    settings_box.label(text="✅ Viewer path is valid", icon='CHECKMARK')
                else:
                    settings_box.label(text="⚠ Viewer file not found", icon='ERROR')
            else:
                settings_box.label(text="⚠ Set viewer path first", icon='ERROR')
        else:
            settings_box.label(text="⚠ Add viewer_html_path to preferences", icon='ERROR')

# ============= REGISTRATION =============
classes = (
    # Property Groups
    GLBFileResult,
    # Preferences
    UnifiedToolkitPreferences,
    # Label Operators
    UNIFIED_OT_create_label,
    UNIFIED_OT_quick_create_label,
    UNIFIED_OT_import_data,
    UNIFIED_OT_fetch_from_ipr,
    UNIFIED_OT_open_ipr_folder,
    UNIFIED_OT_save_ipr_glb,
    UNIFIED_OT_export_data,
    UNIFIED_OT_export_labels_only,
    UNIFIED_OT_edit_properties,
    UNIFIED_OT_shift_animation,
    UNIFIED_OT_add_timeline_markers,
    UNIFIED_OT_sync_markers_to_data,
    UNIFIED_OT_remove_all_markers,
    UNIFIED_OT_diagnose_animation,
    UNIFIED_OT_fix_animation_range,
    UNIFIED_OT_export_glb,
    UNIFIED_OT_add_word_to_dictionary,
    UNIFIED_OT_toggle_performance_monitor,
    UNIFIED_OT_check_for_updates,
    UNIFIED_OT_open_preferences,
    # Asset Library Operators
    UNIFIED_OT_search_glb_files,
    UNIFIED_OT_import_glb_file,
    UNIFIED_OT_upload_glb_file,
    # Quick Shortcuts Operators
    UNIFIED_OT_rename_objects,
    UNIFIED_OT_rename_materials,
    UNIFIED_OT_resize_textures_1024,
    UNIFIED_OT_resize_textures_512,
    # Photoshop Integration Operators
    PS_OT_export_uv_layout,
    PS_OT_export_render_reference,
    PS_OT_open_in_photoshop,
    PS_OT_import_textures_smart,
    PS_OT_reload_all_textures,
    PS_OT_open_texture_folder,
    # Substance Painter Integration Operators
    SP_OT_export_glb,
    SP_OT_open_substance,
    SP_OT_import_glb,
    SP_OT_import_latest,
    SP_OT_cleanup_unused,
    # Spell Check Operators
    UNIFIED_OT_spell_check_now,
    UNIFIED_OT_toggle_ignore_issue,
    UNIFIED_OT_edit_properties_helper,
    # 3D Viewer IPR Operators
    VIEWER_OT_ipr_start,
    VIEWER_OT_ipr_stop,
    # Panels
    UNIFIED_PT_main_panel,
    UNIFIED_PT_labels_panel,
    UNIFIED_PT_asset_library_panel,
    UNIFIED_PT_quick_shortcuts_panel,
    UNIFIED_PT_photoshop_panel,
    UNIFIED_PT_substance_panel,
    UNIFIED_PT_spell_check_panel,
    UNIFIED_PT_viewer_panel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    
    bpy.types.Scene.glb_search_query = bpy.props.StringProperty(name="Search Query")
    bpy.types.Scene.glb_file_results = bpy.props.CollectionProperty(type=GLBFileResult)
    bpy.types.Scene.rename_selected_only = bpy.props.BoolProperty(
        name="Selected Only",
        description="Rename only selected objects/materials",
        default=False
    )
    bpy.types.Scene.spelling_spotter_enabled = bpy.props.BoolProperty(
        name="Enable Online Spellcheck",
        description="Check spelling using LanguageTool API",
        default=False
    )
    bpy.types.Scene.spelling_spotter_cache_json = bpy.props.StringProperty(
        name="Spelling Cache",
        default=""
    )
    bpy.types.Scene.show_performance_stats = bpy.props.BoolProperty(
        name="Show Performance Stats",
        description="Display performance monitoring statistics",
        default=False,
        update=lambda self, context: context.area.tag_redraw() if context.area else None
    )
    
    # Export Settings
    bpy.types.Scene.export_frame_range_enabled = bpy.props.BoolProperty(
        name="Use Scene Frame Range",
        description="Export only frames within scene timeline (ON) or all keyframes (OFF)",
        default=True
    )
    bpy.types.Scene.export_nla_combined = bpy.props.BoolProperty(
        name="Combine NLA Tracks",
        description="Merge all NLA tracks into a single animation",
        default=True
    )

    # Add performance monitoring draw handler
    _draw_handlers.append(bpy.types.SpaceView3D.draw_handler_add(
        draw_performance_stats, (None,), 'WINDOW', 'POST_PIXEL'))

    # Register keyboard shortcuts
    wm = bpy.context.window_manager
    if wm.keyconfigs.addon:
        km = wm.keyconfigs.addon.keymaps.new(name='Object Mode', space_type='EMPTY')
        kmi = km.keymap_items.new('unified.quick_create_label', 'Q', 'PRESS', ctrl=True, shift=True)
        kmi = km.keymap_items.new('unified.toggle_performance_monitor', 'P', 'PRESS', ctrl=True, shift=True)

def unregister():
    # Cleanup IPR server if running
    if ipr_server_state['server']:
        try:
            ipr_server_state['server'].shutdown()
            ipr_server_state['server'].server_close()
            if ipr_server_state['temp_dir'] and os.path.exists(ipr_server_state['temp_dir']):
                shutil.rmtree(ipr_server_state['temp_dir'])
        except:
            pass
    
    # Remove drawing handlers
    for handler in _draw_handlers:
        bpy.types.SpaceView3D.draw_handler_remove(handler, 'WINDOW')
    _draw_handlers.clear()
    
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    
    del bpy.types.Scene.glb_search_query
    del bpy.types.Scene.glb_file_results
    del bpy.types.Scene.rename_selected_only
    del bpy.types.Scene.spelling_spotter_enabled
    del bpy.types.Scene.spelling_spotter_cache_json
    del bpy.types.Scene.show_performance_stats
    del bpy.types.Scene.export_frame_range_enabled
    del bpy.types.Scene.export_nla_combined

    # Unregister keyboard shortcuts
    wm = bpy.context.window_manager
    if wm.keyconfigs.addon:
        km = wm.keyconfigs.addon.keymaps.get('Object Mode')
        if km:
            for kmi in km.keymap_items:
                if kmi.idname in ['unified.quick_create_label', 'unified.toggle_performance_monitor']:
                    km.keymap_items.remove(kmi)

if __name__ == "__main__":
    register()

