import streamlit as st
import base64
import zlib
import io

def base64_encode(data: bytes) -> str:
    return base64.b64encode(data).decode('utf-8')

def obfuscate_python_code(source_code: str, use_compression: bool = False, template: str = "standard") -> str:
    source_bytes = source_code.encode('utf-8')
    
    if use_compression:
        compressed = zlib.compress(source_bytes, level=9)
        b64 = base64_encode(compressed)
        loader = f'''import base64, zlib
b = b"""{b64}"""
try:
    src = zlib.decompress(base64.b64decode(b))
except Exception:
    raise SystemExit('Decoding failed')
exec(src, globals())
'''
    else:
        b64 = base64_encode(source_bytes)
        loader = f'''import base64, zlib
b = b"""{b64}"""
try:
    src = base64.b64decode(b)
except Exception:
    raise SystemExit('Decoding failed')
exec(src, globals())
'''
    
    if template == "compact":
        if use_compression:
            loader = f'''import base64,zlib;exec(zlib.decompress(base64.b64decode(b"""{b64}""")),globals())'''
        else:
            loader = f'''import base64;exec(base64.b64decode(b"""{b64}"""),globals())'''
    elif template == "obfuscated":
        if use_compression:
            loader = f'''import base64,zlib
_x=b"""{b64}"""
_y=base64.b64decode
_z=zlib.decompress
exec(_z(_y(_x)),globals())
'''
        else:
            loader = f'''import base64
_x=b"""{b64}"""
_y=base64.b64decode
exec(_y(_x),globals())
'''
    
    return loader

def deobfuscate_python_code(obfuscated_code: str) -> str:
    try:
        import re
        b64_pattern = r'b"""([A-Za-z0-9+/=\n]+)"""'
        match = re.search(b64_pattern, obfuscated_code)
        
        if not match:
            return "Error: Could not find Base64 encoded data in the file"
        
        b64_data = match.group(1).replace('\n', '')
        decoded = base64.b64decode(b64_data)
        
        if b'zlib.decompress' in obfuscated_code.encode() or b'_z=zlib.decompress' in obfuscated_code.encode():
            try:
                decompressed = zlib.decompress(decoded)
                return decompressed.decode('utf-8')
            except:
                pass
        
        return decoded.decode('utf-8')
    except Exception as e:
        return f"Error during deobfuscation: {str(e)}"

st.set_page_config(
    page_title="Python Code Obfuscator",
    page_icon="🔒",
    layout="wide"
)

st.title("🔒 Python Code Obfuscator")
st.markdown("Obfuscate and deobfuscate Python files using Base64 encoding with optional compression")

tab1, tab2 = st.tabs(["🔒 Obfuscate", "🔓 Deobfuscate"])

with tab1:
    st.subheader("Obfuscate Python Files")
    
    col_left, col_right = st.columns([2, 1])
    
    with col_right:
        st.markdown("#### Options")
        use_compression = st.checkbox(
            "Enable Compression",
            value=False,
            help="Use zlib compression to reduce file size before encoding"
        )
        
        template_option = st.selectbox(
            "Loader Template",
            options=["standard", "compact", "obfuscated"],
            help="Choose the loader template style"
        )
        
        template_descriptions = {
            "standard": "Readable with clear error handling",
            "compact": "Single-line minimal code",
            "obfuscated": "Uses variable name obfuscation"
        }
        st.caption(f"ℹ️ {template_descriptions[template_option]}")
    
    with col_left:
        uploaded_files = st.file_uploader(
            "Choose Python file(s)",
            type=['py'],
            accept_multiple_files=True,
            help="Upload one or more .py files to obfuscate"
        )
    
    if uploaded_files:
        st.markdown("---")
        
        for idx, uploaded_file in enumerate(uploaded_files):
            with st.expander(f"📄 {uploaded_file.name}", expanded=len(uploaded_files) == 1):
                source_code = uploaded_file.read().decode('utf-8')
                original_size = len(source_code)
                
                st.success(f"✓ Loaded: {original_size} bytes")
                
                with st.expander("View Original Code", expanded=False):
                    st.code(source_code, language='python', line_numbers=True)
                
                obfuscated_code = obfuscate_python_code(source_code, use_compression, template_option)
                obfuscated_size = len(obfuscated_code)
                
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Original Size", f"{original_size} bytes")
                with col2:
                    st.metric("Obfuscated Size", f"{obfuscated_size} bytes")
                with col3:
                    size_change = ((obfuscated_size - original_size) / original_size) * 100
                    st.metric("Size Change", f"{size_change:+.1f}%")
                with col4:
                    if use_compression:
                        compressed_size = len(zlib.compress(source_code.encode('utf-8'), level=9))
                        compression_ratio = (1 - compressed_size / original_size) * 100
                        st.metric("Compression", f"{compression_ratio:.1f}%")
                    else:
                        st.metric("Compression", "N/A")
                
                with st.expander("Preview Obfuscated Code", expanded=False):
                    st.code(obfuscated_code, language='python', line_numbers=True)
                
                output_filename = uploaded_file.name.replace('.py', '_obfuscated.py')
                
                st.download_button(
                    label=f"⬇️ Download {output_filename}",
                    data=obfuscated_code,
                    file_name=output_filename,
                    mime="text/x-python",
                    key=f"download_{idx}",
                    use_container_width=True
                )
        
        if len(uploaded_files) > 1:
            st.info(f"✓ Processed {len(uploaded_files)} files successfully")
    
    else:
        st.info("👆 Upload one or more Python files to get started")
        
        with st.expander("ℹ️ How Obfuscation Works"):
            st.markdown("""
            This tool obfuscates Python code using Base64 encoding:
            
            1. **Upload**: Select one or more Python (.py) files
            2. **Compress** (optional): Apply zlib compression to reduce size
            3. **Encode**: Convert to Base64 encoding
            4. **Wrap**: Add a Python loader template that decodes and executes
            5. **Download**: Get your obfuscated files
            
            **Template Options:**
            - **Standard**: Clear, readable loader with error handling
            - **Compact**: Minimal single-line loader
            - **Obfuscated**: Uses obscure variable names for extra obfuscation
            
            **Note**: This provides basic obfuscation, not encryption or strong security.
            """)

with tab2:
    st.subheader("Deobfuscate Python Files")
    st.markdown("Upload an obfuscated file to recover the original source code")
    
    deobf_file = st.file_uploader(
        "Choose an obfuscated Python file",
        type=['py'],
        help="Upload a previously obfuscated .py file",
        key="deobf_uploader"
    )
    
    if deobf_file:
        obfuscated_content = deobf_file.read().decode('utf-8')
        
        st.success(f"✓ Loaded: {deobf_file.name}")
        
        with st.expander("View Obfuscated Code", expanded=False):
            st.code(obfuscated_content, language='python', line_numbers=True)
        
        deobfuscated = deobfuscate_python_code(obfuscated_content)
        
        if deobfuscated.startswith("Error"):
            st.error(deobfuscated)
        else:
            st.success("✓ Successfully deobfuscated!")
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Obfuscated Size", f"{len(obfuscated_content)} bytes")
            with col2:
                st.metric("Deobfuscated Size", f"{len(deobfuscated)} bytes")
            
            with st.expander("View Deobfuscated Code", expanded=True):
                st.code(deobfuscated, language='python', line_numbers=True)
            
            output_filename = deobf_file.name.replace('_obfuscated.py', '_recovered.py')
            if output_filename == deobf_file.name:
                output_filename = deobf_file.name.replace('.py', '_recovered.py')
            
            st.download_button(
                label="⬇️ Download Deobfuscated File",
                data=deobfuscated,
                file_name=output_filename,
                mime="text/x-python",
                use_container_width=True
            )
    else:
        st.info("👆 Upload an obfuscated file to recover the original code")
        
        with st.expander("ℹ️ How Deobfuscation Works"):
            st.markdown("""
            This tool can reverse the obfuscation process:
            
            1. **Upload**: Select an obfuscated Python file
            2. **Extract**: Find the Base64 encoded data
            3. **Decompress** (if applicable): Apply zlib decompression
            4. **Decode**: Convert from Base64 back to original code
            5. **Download**: Get your recovered source code
            
            **Supported formats:**
            - Files obfuscated with this tool
            - Files with standard Base64 encoding
            - Files with compression + Base64 encoding
            """)

st.markdown("---")
st.caption("Built with Streamlit • Python Code Obfuscator & Deobfuscator")
