# -*- coding: utf-8 -*-
"""
@UnrealClaude Script
@Description: (예시 템플릿) layout.json 으로 마을 조립(houses+props+dusk) 후 렌더.
  ★ 이 파일은 .example 템플릿이다. 아래 /Game/Husamguk/... 에셋 경로는 후삼국 예시이며,
    실제 프로젝트에서는 그 프로젝트의 콘텐츠 루트로 교체해야 한다(하드코딩 그대로 쓰지 말 것).
    권장: 환경변수 VRKIT_UE_CONTENT_ROOT 로 콘텐츠 루트를 주입하도록 파라미터화(추후).
"""
import unreal, math, json, traceback, os

# 스크래치 폴더: 죽은 세션 경로를 하드코딩하지 않는다 → 환경변수/기본값.
SCR = os.environ.get("VRKIT_SCRATCH") or os.path.join(os.path.expanduser("~"), "Desktop", "vr_scratch")
os.makedirs(SCR, exist_ok=True)
LAYOUT = os.path.join(SCR, "layout.json")
OUT_NAME = "village.png"
W, H = 1280, 720

with open(LAYOUT, encoding="utf-8") as f:
    L = json.load(f)

def load(p): return unreal.EditorAssetLibrary.load_asset(p)
HANOK = load("/Game/Husamguk/Hanok/hanok_v5/StaticMeshes/hanok_v5.hanok_v5")
M_HANOK= load("/Game/Husamguk/Hanok/M_Hanok.M_Hanok")
M_wood = load("/Game/Husamguk/Props/M_Wood.M_Wood")
M_stone= load("/Game/Husamguk/Props/M_Stone.M_Stone")
M_thatch=load("/Game/Husamguk/Props/M_Thatch.M_Thatch")
M_leaf = load("/Game/Husamguk/Props/M_Leaf.M_Leaf")
CYL=load("/Engine/BasicShapes/Cylinder.Cylinder"); CUBE=load("/Engine/BasicShapes/Cube.Cube")
CONE=load("/Engine/BasicShapes/Cone.Cone"); SPH=load("/Engine/BasicShapes/Sphere.Sphere")
PLANE=load("/Engine/BasicShapes/Plane.Plane")

# --- extra materials (ground/water/emissive/smoke) ---
mel = unreal.MaterialEditingLibrary
_tools = unreal.AssetToolsHelpers.get_asset_tools()
def make_mat(name, rgb, rough=0.85, emissive=None, translucent=False, opacity=1.0):
    path = "/Game/Husamguk/Props/" + name
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        return unreal.EditorAssetLibrary.load_asset(path + "." + name)
    m = _tools.create_asset(name, "/Game/Husamguk/Props", unreal.Material, unreal.MaterialFactoryNew())
    col = mel.create_material_expression(m, unreal.MaterialExpressionConstant3Vector, -500, 0)
    col.set_editor_property("constant", unreal.LinearColor(rgb[0],rgb[1],rgb[2],1.0))
    mel.connect_material_property(col, "", unreal.MaterialProperty.MP_BASE_COLOR)
    r = mel.create_material_expression(m, unreal.MaterialExpressionConstant, -500, 200)
    r.set_editor_property("r", rough); mel.connect_material_property(r, "", unreal.MaterialProperty.MP_ROUGHNESS)
    if emissive is not None:
        e = mel.create_material_expression(m, unreal.MaterialExpressionConstant3Vector, -500, 380)
        e.set_editor_property("constant", unreal.LinearColor(emissive[0],emissive[1],emissive[2],1.0))
        mel.connect_material_property(e, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    if translucent:
        m.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
        op = mel.create_material_expression(m, unreal.MaterialExpressionConstant, -500, 560)
        op.set_editor_property("r", opacity); mel.connect_material_property(op, "", unreal.MaterialProperty.MP_OPACITY)
    mel.recompile_material(m); unreal.EditorAssetLibrary.save_asset(m.get_path_name()); return m

M_ground = make_mat("M_Ground", (0.20,0.16,0.10), 0.95)
M_path   = make_mat("M_Path",   (0.30,0.24,0.15), 0.95)
M_water  = make_mat("M_Water",  (0.012,0.045,0.06), 0.035)  # 반사 수면(노을·하늘 반영)
if unreal.EditorAssetLibrary.does_asset_exist("/Game/Husamguk/Props/M_Flame"):
    unreal.EditorAssetLibrary.delete_asset("/Game/Husamguk/Props/M_Flame")
M_flame  = make_mat("M_Flame",  (1.0,0.4,0.1), 0.8, emissive=(5.5,1.7,0.35))  # 주황 불꽃(발광 강)
M_lantern= make_mat("M_Lantern",(1.0,0.75,0.35), 0.8, emissive=(4.5,3.0,1.2))
M_smoke  = make_mat("M_Smoke",  (0.5,0.5,0.5), 1.0, translucent=True, opacity=0.22)
M_talis  = make_mat("M_Talis",  (0.6,0.85,1.0), 0.7, emissive=(0.8,2.4,4.5))
M_float  = make_mat("M_Float",  (1.0,0.5,0.18), 0.6, emissive=(3.0,1.05,0.28))  # 떠다니는 등불(따뜻한 호박색)

eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
ar = unreal.AssetRegistryHelpers.get_asset_registry()

def find_ai(name):
    dest = "/Game/Husamguk/AIProps/" + name
    meshpath = None
    for a in ar.get_assets_by_path(dest, recursive=True):
        if str(a.asset_class_path.asset_name) == "StaticMesh":
            meshpath = str(a.package_name) + "." + str(a.asset_name); break
    if not meshpath: return None, None
    mesh = unreal.EditorAssetLibrary.load_asset(meshpath)
    mpath = "/Game/Husamguk/AIProps/M_%s_AI" % name
    mat = unreal.EditorAssetLibrary.load_asset(mpath + "." + "M_%s_AI"%name) if unreal.EditorAssetLibrary.does_asset_exist(mpath) else None
    return mesh, mat

def place_ai(name, bx, by, target_h, yaw=0.0, label=None):
    mesh, mat = find_ai(name)
    if not mesh: return False
    b = mesh.get_bounds(); ez = b.box_extent.z
    s = (target_h/(2.0*ez)) if ez>0 else 1.0
    a = eas.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(bx,by, ez*s), unreal.Rotator(0,0,yaw))
    a.set_actor_label(label or ("AI_%s"%name))
    c = a.static_mesh_component; c.set_static_mesh(mesh)
    if mat:
        for i in range(c.get_num_materials()): c.set_material(i, mat)
    a.set_actor_scale3d(unreal.Vector(s,s,s))
    return True

def _centroid_h(L): return (sum(h[0] for h in L["houses"])/len(L["houses"]), sum(h[1] for h in L["houses"])/len(L["houses"]))

def place_grove_ai(L):
    cx,cy = _centroid_h(L)
    spots = [(cx-1500,cy+300,0.95,20),(cx+1750,cy-650,1.15,-30),(cx-1000,cy-1150,1.0,60),
             (cx+1000,cy+1300,0.85,110),(cx-1950,cy+950,1.05,200),(cx+2050,cy+800,0.9,-70),
             (cx-300,cy-1500,0.9,150),(cx+300,cy+1650,1.0,300)]
    for i,(x,y,s,yaw) in enumerate(spots):
        place_ai("Tree", x, y, 520*s, yaw, label="AI_Grove_%02d"%i)

def build_wall(L):
    # 성벽 블록아웃: 긴 돌벽 + 마을쪽 흉벽(총안) + 올라가는 계단. 카메라~마을 사이에 배치.
    cx,cy = _centroid_h(L)
    camx,camy = L["cam"][0], L["cam"][1]
    wcx = cx + (camx-cx)*0.40; wcy = cy + (camy-cy)*0.40   # 마을 가장자리(카메라쪽 40%)
    view = math.atan2(cy-wcy, cx-wcx)                       # 벽→마을 방향
    yaw = math.degrees(view) + 90.0                         # 벽 길이축 = 시선 수직
    r = math.radians(yaw); ux,uy = math.cos(r), math.sin(r)
    vx,vy = math.cos(view), math.sin(view)                  # 마을 쪽 단위벡터
    def wpart(a,p,z,sx,sy,sz,lab):
        spawn(CUBE, M_stone, wcx+a*ux+p*vx, wcy+a*uy+p*vy, z, (sx,sy,sz), (0,0,yaw), "Fort_"+lab)
    # 본체 성벽 (윗면이 순찰로/walkway)
    wpart(0,0,290, 46,5.0,5.8, "body")
    # 지대석(하단 넓게)
    wpart(0,0,45, 48,6.2,0.9, "base")
    # 마을쪽 흉벽 + 총안(merlon 사이 gap)
    a=-2100; k=0
    while a<=2100:
        wpart(a, 235, 660, 1.7,1.1,1.6, "merlon%d"%k); a+=520; k+=1
    # 반대쪽(뒤) 난간
    wpart(0,-235,650, 46,0.7,1.2, "backrail")
    # 올라가는 계단 (뒤쪽 한쪽 끝)
    for s in range(7):
        wpart(-2000, -320 - s*95, 75 + s*80, 7.5,1.35,0.85, "stair%d"%s)
    return (wcx,wcy,yaw)

def place_figures_ai(L):
    cx,cy = _centroid_h(L)
    place_ai("Person", cx-160, cy-210, 175, 30, "AI_Person0")
    place_ai("Person", cx+240, cy-40, 175, -60, "AI_Person1")
    place_ai("Person", cx+40, cy+300, 175, 160, "AI_Person2")
    place_ai("Cow", cx-330, cy+170, 155, 20, "AI_Cow0")
    place_ai("Chicken", cx+70, cy-130, 45, 0, "AI_Chicken0")
    place_ai("Chicken", cx+110, cy-165, 45, 40, "AI_Chicken1")
    place_ai("Dog", cx+260, cy+150, 78, 60, "AI_Dog0")

# clear all managed actors
for a in list(eas.get_all_level_actors()):
    lbl = a.get_actor_label()
    if lbl.startswith(("Village_","Well_","Wheel_","Tree_","Rock_","Env_","Fx_","Fig_","AI_","Fort_")) or a.get_name()=="Hanok_01":
        eas.destroy_actor(a)

def spawn(mesh, mat, wx, wy, z, scale, rot=(0,0,0), label="X"):
    a = eas.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(wx,wy,z), unreal.Rotator(*rot))
    a.set_actor_label(label)
    c=a.static_mesh_component; c.set_static_mesh(mesh)
    if isinstance(mat, list):
        for i,m in enumerate(mat): c.set_material(i,m)
    else:
        for i in range(c.get_num_materials()): c.set_material(i, mat)
    a.set_actor_scale3d(unreal.Vector(*scale)); return a

# ---- houses (varied structures: AI variants + emissive-window hanok_v5) ----
HOUSE_VAR = ["HouseA","hanok","HouseC","HouseB","HouseA","hanok","HouseC","HouseA","HouseB"]
HOUSE_H = {"HouseA":380.0, "HouseC":400.0, "HouseB":470.0}
for i,(x,y,yaw,s) in enumerate(L["houses"]):
    v = HOUSE_VAR[i % len(HOUSE_VAR)]
    lbl = "Village_Hanok_%02d"%i
    if v=="hanok" or not place_ai(v, x, y, HOUSE_H.get(v,400.0)*s, yaw, lbl):
        spawn(HANOK, M_HANOK, x, y, 154*s, (s,s,s), (0,0,yaw), lbl)

# ---- well ----
def build_well(bx,by):
    n=[0]
    def p(m,mat,dx,dy,z,sc,rot=(0,0,0)):
        spawn(m,mat,bx+dx,by+dy,z,sc,rot,"Well_%02d"%n[0]); n[0]+=1
    p(CYL,M_stone,0,0,55,(1.6,1.6,1.1)); p(CYL,M_stone,0,0,112,(1.75,1.75,0.12))
    p(CYL,M_wood,0,0,100,(1.25,1.25,0.05))
    p(CUBE,M_wood,-78,0,150,(0.14,0.14,3.0)); p(CUBE,M_wood,78,0,150,(0.14,0.14,3.0))
    p(CUBE,M_wood,0,0,298,(1.75,0.16,0.16)); p(CONE,M_thatch,0,0,330,(2.4,2.4,0.9))
    p(CYL,M_wood,0,0,175,(0.4,0.4,0.35)); p(CUBE,M_wood,0,0,240,(0.04,0.04,1.3))

# ---- water wheel ----
def build_wheel(bx,by):
    n=[0]; CZ=210.0; R=180.0; disc=(R/50.0,R/50.0,0.10)
    def p(m,mat,dx,dy,z,sc,rot=(0,0,0)):
        spawn(m,mat,bx+dx,by+dy,z,sc,rot,"Wheel_%02d"%n[0]); n[0]+=1
    p(CYL,M_wood,0,55,CZ,disc,(90,0,0)); p(CYL,M_wood,0,-55,CZ,disc,(90,0,0))
    p(CYL,M_stone,0,0,CZ,(R/50.0*0.35,R/50.0*0.35,1.2),(90,0,0)); p(CYL,M_wood,0,0,CZ,(0.35,0.35,2.2),(90,0,0))
    for k in range(8):
        a=2*math.pi*k/8; p(CUBE,M_wood,R*math.cos(a),0,CZ+R*math.sin(a),(0.12,1.25,0.55),(0,math.degrees(a),0))
    for sx in (1,-1):
        p(CUBE,M_wood,sx*(R+40),70,CZ*0.5,(0.22,0.22,(CZ+40)/100.0)); p(CUBE,M_wood,sx*(R+40),-70,CZ*0.5,(0.22,0.22,(CZ+40)/100.0))
    p(CUBE,M_stone,0,0,25,(2.2,2.0,0.5)); p(CUBE,M_stone,360,0,110,(1.4,2.0,2.1)); p(CUBE,M_wood,360,0,235,(1.8,2.4,0.28))

# ---- sacred tree ----
def build_tree(bx,by):
    n=[0]
    def p(m,mat,dx,dy,z,sc,rot=(0,0,0)):
        spawn(m,mat,bx+dx,by+dy,z,sc,rot,"Tree_%02d"%n[0]); n[0]+=1
    p(CYL,M_wood,0,0,280,(0.9,0.9,5.6),(0,3,0))
    p(CYL,M_wood,60,20,470,(0.3,0.3,2.2),(0,55,0)); p(CYL,M_wood,-55,-10,500,(0.28,0.28,2.0),(0,-50,0))
    for (lx,ly,lz,s) in [(0,0,660,6.0),(150,70,600,4.2),(-140,-50,620,4.4),(50,-140,600,3.9),(-70,140,600,3.7),(0,0,760,3.4)]:
        p(SPH,M_leaf,lx,ly,lz,(s,s,s))
    p(CYL,M_stone,0,0,18,(2.4,2.4,0.35))
    p(SPH,M_stone,170,120,35,(0.9,0.9,0.9)); p(SPH,M_stone,185,120,90,(0.7,0.7,0.7)); p(SPH,M_stone,195,120,130,(0.5,0.5,0.5))

# ---- rocks ----
def build_rocks(bx,by):
    n=[0]
    specs=[((0,0,20),(1.8,1.5,1.1),(10,20,5)),((150,60,15),(1.1,1.4,0.9),(5,40,15)),
           ((-120,80,12),(0.9,0.8,0.7),(20,10,8)),((60,-140,14),(1.3,1.0,0.85),(0,60,12)),
           ((-90,-110,10),(0.7,0.9,0.6),(15,30,0)),((220,-40,10),(0.6,0.7,0.5),(8,25,10))]
    for (loc,sc,rot) in specs:
        spawn(SPH,M_stone,bx+loc[0],by+loc[1],loc[2],sc,rot,"Rock_%02d"%n[0]); n[0]+=1

def plight(wx,wy,z,color,intensity,radius,label):
    a=eas.spawn_actor_from_class(unreal.PointLight, unreal.Vector(wx,wy,z))
    a.set_actor_label(label)
    pc=a.get_component_by_class(unreal.PointLightComponent)
    try: pc.set_editor_property("intensity_units", unreal.LightUnits.LUMENS)
    except Exception: pass
    pc.set_editor_property("intensity", float(intensity))
    try: pc.set_editor_property("use_temperature", False)
    except Exception: pass
    # FColor 위치인자는 BGRA로 뒤집혀 파랑이 됨 → set_light_color(LinearColor)로 명확히
    pc.set_light_color(unreal.LinearColor(float(color[0]), float(color[1]), float(color[2]), 1.0))
    pc.set_editor_property("attenuation_radius", float(radius))
    return a

def centroid(hs): return (sum(h[0] for h in hs)/len(hs), sum(h[1] for h in hs)/len(hs))

def setup_ground(L):
    n=[0]
    # earth material on the default Floor
    for a in eas.get_all_level_actors():
        if a.get_actor_label()=="Floor":
            try:
                c=a.get_component_by_class(unreal.StaticMeshComponent)
                for i in range(c.get_num_materials()): c.set_material(i, M_ground)
            except Exception: pass
    cx,cy = centroid(L["houses"])
    # dirt path segments through the village
    for (px,py,sx,sy,yaw) in [(cx,cy,0.55,16.0,20),(cx-500,cy+600,0.5,10.0,70),(cx+700,cy-300,0.5,9.0,-25)]:
        spawn(PLANE, M_path, px, py, 3, (sx,sy,1), (0,0,yaw), "Env_Path_%02d"%n[0]); n[0]+=1
    # 물레방아를 지나는 긴 개천(강) + 마을 연못
    wx,wy = L["wheel"]
    spawn(PLANE, M_water, wx+90, wy, 3, (9.0, 48.0, 1), (0,0,0), "Env_Water_river")
    spawn(PLANE, M_water, cx-250, cy-1500, 3, (12.0, 12.0, 1), (0,0,0), "Env_Water_pond")

def setup_effects(L):
    n=[0]
    # 집 창문 실내 불빛(호롱불) — 전부 동일 주황색으로 통일 (사용자 지정 2026-08-24)
    HOME_ORANGE = (1.0, 0.5, 0.16)
    for i,(x,y,yaw,s) in enumerate(L["houses"]):
        ox = x + 55*math.cos(math.radians(yaw)); oy = y + 55*math.sin(math.radians(yaw))
        plight(ox, oy, 130, HOME_ORANGE, 400, 520, "Fx_HomeGlow_%02d"%i)
    # 모닥불: AI 메시(돌화덕+장작+불꽃) + 불빛 라이트. AI 없으면 프리미티브 폴백.
    cx,cy = centroid(L["houses"]); fx,fy = cx+250, cy-350
    if not place_ai("Campfire", fx, fy, 130, 0, "Fx_Campfire"):
        for k in range(6):
            a=2*math.pi*k/6
            spawn(CUBE, M_wood, fx+35*math.cos(a), fy+35*math.sin(a), 12, (0.5,0.12,0.12), (0,0,math.degrees(a)), "Fx_Log_%02d"%k)
        for k in range(4):
            spawn(CONE, M_flame, fx+ (k-1.5)*8, fy, 45+ k%2*10, (0.5,0.5,1.1), (0,0,0), "Fx_Flame_%02d"%k)
    # 주황 발광 불꽃 (사용자 지정 주황색 유지)
    for k in range(3):
        spawn(SPH, M_flame, fx+(k-1)*12, fy+(k%2)*8, 80+k*11, (0.16,0.16,0.28), (0,0,0), "Fx_FlameGlow_%02d"%k)
    plight(fx, fy, 90, (1.0,0.5,0.16), 1200, 720, "Fx_FireLight")
    # chimney smoke on MULTIPLE houses (필수#6: 여러 채)
    for hi in range(min(4, len(L["houses"]))):
        hx,hy,hyaw,hs = L["houses"][hi]
        for k in range(5):
            spawn(SPH, M_smoke, hx+110+k*16, hy+25, 350+k*85, (0.55+0.12*k,)*3, (0,0,0), "Env_Smoke_%d_%d"%(hi,k))
    # 떠다니는 등불 (강도#4): floating warm orbs above the village
    cx,cy = centroid(L["houses"])
    # 떠다니는 등불: 더 높게, 넓게, 따뜻한 호박색 (물방울 모양)
    fl = [(-350,-450,620),(540,220,760),(-720,540,700),(320,-820,650),(830,-350,820),
          (-160,560,880),(700,780,720),(1300,-200,780),(-1300,-100,700),(150,1250,760),
          (-900,-700,660),(1000,1100,840),(-500,1300,720)]
    for i,(dx,dy,dz) in enumerate(fl):
        spawn(SPH, M_float, cx+dx, cy+dy, dz, (0.30,0.30,0.40), (0,0,0), "Fx_Float_%02d"%i)
        plight(cx+dx, cy+dy, dz, (1.0,0.55,0.20), 300, 460, "Fx_FloatL_%02d"%i)
    # 당산나무 빛나는 부적(파란 천 strips) + 나무 하단 조명
    tx,ty = L["tree"]
    for i,(dx,dy,dz) in enumerate([(120,60,430),(80,-110,400),(-130,40,455),(-70,-95,410),(165,-30,470),(-160,-60,420)]):
        spawn(CUBE, M_talis, tx+dx, ty+dy, dz, (0.05,0.13,1.5), (0,0,0), "Fx_Talis_%02d"%i)
    plight(tx, ty, 480, (0.55,0.78,1.0), 700, 650, "Fx_TreeGlow")
    # 반딧불/공중 글로우 점 (warm)
    for i,(dx,dy,dz) in enumerate([(-250,320,120),(430,-220,95),(760,320,150),(-560,-120,110),(220,640,100),
                                    (980,-430,135),(-860,240,125),(320,-560,95),(650,120,160),(-360,-460,110)]):
        spawn(SPH, M_lantern, cx+dx, cy+dy, dz, (0.055,0.055,0.055), (0,0,0), "Fx_FF_%02d"%i)

def build_grove(L):
    # 일반 수목: trunk + 2-3 foliage spheres, scattered around village edges
    for i,(x,y,s) in enumerate(L.get("trees", [])):
        spawn(CYL, M_wood, x, y, 150*s, (0.55*s,0.55*s,3.0*s), (0,2,0), "Env_Grove_%dT"%i)
        for j,(ox,oy,oz,r) in enumerate([(0,0,360,3.0),(60,30,320,2.2),(-55,-20,330,2.3),(20,-60,320,2.0)]):
            spawn(SPH, M_leaf, x+ox*s, y+oy*s, oz*s, (r*s,r*s,r*s), (0,0,0), "Env_Grove_%dF%d"%(i,j))

def build_figures(L):
    # 사람·동물 정적 실루엣 (후순위, 원거리용): 집/길 주변에 소수
    cx,cy = centroid(L["houses"])
    M_cloth = make_mat("M_Cloth", (0.35,0.32,0.28), 0.9)
    M_skin  = make_mat("M_Skin",  (0.62,0.46,0.34), 0.85)
    M_cow   = make_mat("M_Cow",   (0.18,0.13,0.10), 0.9)
    def person(px,py,label):
        spawn(CYL, M_cloth, px,py,52, (0.32,0.32,1.05), (0,0,0), label+"b")   # body/robe
        spawn(SPH, M_skin,  px,py,118,(0.34,0.34,0.34), (0,0,0), label+"h")   # head
    def cow(px,py,yaw,label):
        spawn(CUBE, M_cow, px,py,70, (1.35,0.62,0.72), (0,0,yaw), label+"B")
        for sx in (-1,1):
            for sy in (-1,1):
                spawn(CUBE, M_cow, px+sx*55,py+sy*22,28, (0.14,0.14,0.56),(0,0,yaw), label+"L%d%d"%(sx,sy))
        spawn(CUBE, M_cow, px+ (78 if yaw%360<90 else 78), py, 82, (0.5,0.42,0.42),(0,0,yaw), label+"H")
    def chicken(px,py,label):
        spawn(SPH, M_skin, px,py,14,(0.16,0.22,0.2),(0,0,0),label+"b")
        spawn(SPH, M_cloth,px,py,26,(0.1,0.1,0.12),(0,0,0),label+"h")
    def dog(px,py,yaw,label):
        spawn(CUBE, M_cow, px,py,26,(0.7,0.24,0.28),(0,0,yaw),label+"b")
        spawn(SPH, M_cow, px+30,py,34,(0.22,0.22,0.22),(0,0,0),label+"h")
    person(cx-120, cy-180, "Fig_P0"); person(cx+180, cy-60, "Fig_P1"); person(cx+60, cy+240, "Fig_P2")
    cow(cx-260, cy+120, 20, "Fig_Cow0")
    chicken(cx+40, cy-120, "Fig_Ck0"); chicken(cx+70, cy-150, "Fig_Ck1")
    dog(cx+220, cy+140, 60, "Fig_Dog0")

try:
  # AI-generated props (Hunyuan3D) with primitive fallback
  if not place_ai("Well",       L["well"][0],  L["well"][1],  240, 15):  build_well(*L["well"])
  if not place_ai("Waterwheel", L["wheel"][0], L["wheel"][1], 430, 90):  build_wheel(*L["wheel"])
  if not place_ai("Dangsan",    L["tree"][0],  L["tree"][1],  760, 0):   build_tree(*L["tree"])
  if not place_ai("Rock",       L["rocks"][0], L["rocks"][1], 210, 30):  build_rocks(*L["rocks"])
  setup_ground(L); setup_effects(L)
  build_wall(L)   # 성벽 블록아웃 (플레이어가 올라갈 순찰로+계단)
  # (2차 배치 제외: 일반나무·사람·동물 AI 생성 보류 — 사용자 지시 2026-08-24)
except Exception as e:
  open(SCR+r"\asm_err.txt","w",encoding="utf-8").write("PROPS:\n"+traceback.format_exc())
  raise

# ---- dusk lighting ----
def find(cn):
    for a in eas.get_all_level_actors():
        if a.get_class().get_name()==cn: return a
    return None
try:
  sp,sy,si = L.get("sun",[-8,55,3.0])
  dl=find("DirectionalLight")
  if dl:
    dl.set_actor_rotation(unreal.Rotator(0.0,float(sp),float(sy)),False)
    dc=dl.get_component_by_class(unreal.DirectionalLightComponent)
    dc.set_editor_property("intensity",float(si)); dc.set_light_color(unreal.LinearColor(1.0,0.72,0.47,1.0))
    try:
        dc.set_editor_property("use_temperature", True); dc.set_editor_property("temperature", 3800.0)
    except Exception: pass
  # ⛔ 기본 SkyLight는 절대 건드리지 않는다 (사용자 지시 2026-08-24). 기본 그대로 둔다.
  fg=find("ExponentialHeightFog")
  if fg:
    fc=fg.get_component_by_class(unreal.ExponentialHeightFogComponent)
    def _fog(prop,val):
        try: fc.set_editor_property(prop,val)
        except Exception: pass
    _fog("fog_density",0.014)
    _fog("fog_height_falloff",0.28)
    _fog("directional_inscattering_color", unreal.LinearColor(1.0,0.45,0.15,1.0))
    _fog("directional_inscattering_exponent", 20.0)
    _fog("directional_inscattering_start_distance", 300.0)
    _fog("volumetric_fog", True)
    _fog("volumetric_fog_scattering_distribution", 0.8)
    _fog("volumetric_fog_extinction_scale", 1.2)

  # ---- render ----
  cx,cy,cz,tx,ty,tz,fov = L.get("cam",[-2600,-2100,1050,200,0,150,72])
  cam=unreal.Vector(cx,cy,cz); tgt=unreal.Vector(tx,ty,tz)
  dx,dy,dz=tgt.x-cam.x,tgt.y-cam.y,tgt.z-cam.z
  yaw=math.degrees(math.atan2(dy,dx)); pitch=math.degrees(math.atan2(dz,math.sqrt(dx*dx+dy*dy)))
  world=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
  RL=unreal.RenderingLibrary
  rt=RL.create_render_target2d(world,W,H,unreal.TextureRenderTargetFormat.RTF_RGBA8)
  cap=eas.spawn_actor_from_class(unreal.SceneCapture2D,cam,unreal.Rotator(0,pitch,yaw))
  cc=cap.get_component_by_class(unreal.SceneCaptureComponent2D)
  cc.set_editor_property("texture_target",rt)
  cc.set_editor_property("capture_source",unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
  cc.set_editor_property("fov_angle",float(fov))
  pp=cc.get_editor_property("post_process_settings")
  pp.set_editor_property("auto_exposure_bias",0.78); pp.set_editor_property("override_auto_exposure_bias",True)
  cc.set_editor_property("post_process_settings",pp)
  cc.capture_scene()
  RL.export_render_target(world,rt,SCR,OUT_NAME)
  eas.destroy_actor(cap)
  print("HOUSES",len(L["houses"]),"CAM",round(cx),round(cy),round(cz))
  print("WROTE",OUT_NAME); print("DONE")
except Exception as e:
  open(SCR+r"\asm_err.txt","w",encoding="utf-8").write("RENDER:\n"+traceback.format_exc())
  raise
